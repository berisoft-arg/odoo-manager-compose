"""Flujos de dominio: instalador, dependencias, sync, modos prod, crear proyecto.

Sin argparse (eso vive en cli.py). Toda pregunta pasa por tui.ask_*.
"""

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__ as PKG_VERSION
from .tui import (
    es_interactivo,
    ask_texto,
    ask_opcion,
    ask_si_no,
    ask_puerto,
    ask_float,
    preguntar,
    titulo,
    numero,
    tenue,
    texto_menu,
    ok,
    err,
    marco,
    banner_omc,
    seccion,
)
from .core import (
    render,
    cargar_versions,
    cargar_catalogo,
    load_catalog,
    cargar_localizaciones,
    puerto_libre,
    puerto_en_uso,
    parse_addon_spec,
    parse_seleccion,
    reparto_vps,
    bloque_deploy,
    template_text,
    data_text,
    data_path,
    data_path_write,
    projects_home,
    default_salida,
    asegurar_escribible,
    find_proyecto,
    odoo_to_branch,
    read_env_branch,
    leer_env,
    ENTORNOS,
    merge_json,
    sin_renderizar,
)
from .compose import (
    generar_compose,
    generar_odoo_conf,
    parchear_compose_a_build,
)

# Compat alias: código viejo llamaba cargar_template()
cargar_template = template_text
from .github import (
    gh_config_leer,
    gh_config_guardar,
    gh_validar_token,
    gh_token,
    gh_org,
    es_url,
    org_desde_url,
    resolve_repo,
    buscar_modulo as buscar_modulo_en_catalogo,
    KNOWN_ORGS,
)
from .gitutils import (
    git_pull,
    git_red,
    list_remote_topdirs,
    remote_head,
    run,
)
from .manifest import (
    leer_manifest,
    normalizar_req,
    quitar_m2crypto,
    detectar_conflictos,
    iterar_modulos,
    analizar_depends,
    load_repos,
    save_repos,
)
from .addonsops import (
    actualizar_bundle_desde_estado,
    add_modules,
    bundle_install,
    bundle_desde_estado,
    actualizar_addons_path,
    limpiar_symlinks,
)

STUB_ADDONS_TPL = """#!/usr/bin/env python3
# Stub generado por OMC {ver}: delega en el paquete instalado.
# Uso: ./odoo-addons.py <subcomando> [flags]  (equivale a: omc addons ...)
import sys
from pathlib import Path
try:
    from omc.addons_cli import main
except ImportError:
    sys.exit("Falta omc instalado. Instalá con: pip install odoo-manager-compose")
argv = sys.argv[1:]
if "--proyecto" not in argv and "-p" not in argv:
    argv += ["--proyecto", str(Path(__file__).resolve().parent)]
sys.exit(main(argv))
"""


def stub_addons() -> str:
    return STUB_ADDONS_TPL.format(ver=PKG_VERSION)


def instalar_addon(salida, org, repo, modulos, version, url="", branch=None):
    """Descarga directa (sin subproceso). Rama = version.0, NUNCA se pregunta.

    Con branch explícito (ej rama de migración 17.0-mig-*) se usa esa en vez."""
    try:
        add_modules(Path(salida), org, repo, url, branch or odoo_to_branch(version), modulos)
        return True
    except SystemExit:
        return False


def instalar_addon_url(salida, org, repo, url, modulos, version, branch=None):
    return instalar_addon(
        salida, org if org != "otro" else "custom", repo, modulos, version, url, branch
    )


def instalar_bundle(salida, bundle, version):
    """Descarga TODO lo de la plantilla bundle. Rama automática version.0."""
    salida = Path(salida)
    bp = Path(bundle)
    if not bp.is_absolute():
        bp = salida / bundle
    if not bp.exists():
        alt = data_path(Path(bundle).name)
        if alt and alt.exists():
            bp = alt
    if not bp.exists():
        print(f"  ⚠ No existe la plantilla bundle: {bundle}")
        return False
    try:
        data = json.loads(bp.read_text(encoding="utf-8"))
    except ValueError as e:
        print(f"  ⚠ Bundle inválido: {e}")
        return False
    try:
        bundle_install(salida, data, odoo_to_branch(version), load_catalog())
        return True
    except (SystemExit, ValueError) as e:
        print(f"  ⚠ {e}")
        return False


def puerta_instalacion(salida: Path, version: str) -> None:
    """UNA sola puerta: bundle, lista o nada. Reemplaza los gates si/no duplicados."""
    modo = ask_opcion(
        "¿Qué instalar?",
        ["Plantilla bundle (addons-bundle.json)", "Elegir de lista (OCA/AdHoc/...)", "Nada"],
        "Nada",
    )
    if modo.startswith("Plantilla"):
        paso_bundle_interactivo(salida, version, sin_pregunta=True)
    elif modo.startswith("Elegir"):
        paso_addons_interactivo(salida, version, sin_pregunta=True)


def paso_bundle_interactivo(
    salida: Path, version: str, sin_pregunta: bool = False
) -> bool:
    """Ejecuta bundle. Con sin_pregunta=True omite el gate si/no (lo decide puerta_instalacion)."""
    if not sin_pregunta:
        quiere = preguntar(
            "¿Usar plantilla bundle para descargar módulos (todo junto)?",
            "no",
            ["si", "no"],
        )
        if quiere != "si":
            return False
    print(
        "  Plantilla: JSON con repos+módulos. Tienes addons-bundle.ejemplo.json de base."
    )
    print(
        "  Cópialo como addons-bundle.json, llénalo y sigue. Rama automática según tu Odoo."
    )
    bpath = (
        preguntar("Ruta plantilla bundle", "addons-bundle.json").strip()
        or "addons-bundle.json"
    )
    full = Path(bpath) if Path(bpath).is_absolute() else salida / bpath
    if not full.exists():
        print(f"  ⚠ No existe {full}.")
        print("    1) cp addons-bundle.ejemplo.json addons-bundle.json")
        print("    2) edítalo con tus repos/módulos")
        print(f"    3) omc addons bundle {bpath} --odoo {version}")
        return True  # se explicó el camino, no seguir a manual
    return instalar_bundle(salida, bpath, version)


def paso_addons_interactivo(salida: Path, version: str, sin_pregunta: bool = False):
    """Lista OCA/AdHoc/... La branch sale de version, no se pregunta.
    Con sin_pregunta=True omite el gate si/no (lo decide puerta_instalacion)."""
    branch = f"{version}.0"
    catalogo = cargar_catalogo()
    if not sin_pregunta:
        quiere = preguntar("¿Descargar módulos de terceros ahora?", "no", ["si", "no"])
        if quiere != "si":
            return
    print(f"\nRama git automática: {branch}")
    print("Sus módulos propios van directo en addons/custom/ (no necesitan helper).")

    def mostrar_y_elegir(org_label: str, repo: str, url: str, desde_url: bool,
                         rama: str = ""):
        br = rama or branch
        print(f"\nListando módulos de {repo}@{br} ...")
        modulos_disp, unico, ramas = list_remote_topdirs(url, br)
        if modulos_disp is None:
            if ramas is None:
                print(
                    f"  ⚠ No se pudo leer {url} (¿URL mal o privado sin GITHUB_TOKEN?). Prueba otro."
                )
            else:
                hay = ", ".join(ramas) if ramas else "(ninguna X.0)"
                print(f"  ⚠ Sin rama {br}. Disponibles: {hay}.")
            return
        if unico:
            print(f"\n{repo}@{br} ES el módulo (repo de un solo módulo).")
            if (
                preguntar(
                    f"¿Descargar {repo} entero?", "si", ["si", "no"]
                )
                != "si"
            ):
                return
            instalar_addon(salida, org_label if desde_url else "custom",
                             repo, [repo], version, url, branch=br)
            return
        # Checklist primero, fallback a entrada textual
        sel = None
        try:
            from .tui import checklist
            sel = checklist(f"Elige módulos de {repo}@{br} ({len(modulos_disp)})", modulos_disp)
        except Exception:  # noqa: BLE001
            sel = None
        if sel is not None:
            if not sel:
                return
            modulos = [m for m in sel if m in modulos_disp]
            invalidos = []
            if not modulos:
                print("  Nada seleccionado, no se descarga nada.")
                return
        else:
            print(f"\n-- Módulos en {repo}@{br} ({len(modulos_disp)}) --")
            for i, m in enumerate(modulos_disp, 1):
                print(f"  {i:3}) {m}")
            mods_raw = preguntar(
                "Módulos (números, nombres o 'todo'; coma; vacío=ninguno)", ""
            ).strip()
            if not mods_raw:
                return
            modulos, invalidos = parse_seleccion(mods_raw, modulos_disp)
            for inv in invalidos:
                print(f"  ⚠ '{inv}' no existe en {repo}@{br}, omitido.")
            if not modulos:
                print("  Nada válido, no se descarga nada.")
                return
        if desde_url:
            instalar_addon_url(salida, org_label, repo, url, modulos, version, branch=br)
        else:
            instalar_addon(salida, org_label, repo, modulos, version, url, branch=br)

    # Nota: orígenes GitHub salen de github.KNOWN_ORGS (fuente única).
    ORG_NOMBRES = [
        ("oca", "OCA"),
        ("adhoc", "Ad Hoc"),
        ("cybrosys", "Cybrosys"),
        ("mates", "Odoo Mates"),
        ("otro", "Otro"),
        ("listo", "Listo"),
    ]
    while True:
        labels = [v for _k, v in ORG_NOMBRES]
        elegida = ask_opcion(
            "¿Origen?", labels, "Listo", {k: v for k, v in ORG_NOMBRES}
        )
        org = next(k for k, v in ORG_NOMBRES if v == elegida)
        if org == "listo":
            break
        if org == "otro":
            url = preguntar(
                "URL del repo (https o SSH; también PR: te pide la rama. "
                "Privado https: exporta GITHUB_TOKEN antes)",
                "",
            ).strip()
            if not url:
                continue
            repo = url.rstrip("/").split("/")[-1].removesuffix(".git").split(":")[-1]
            rama_pr = ""
            if ask_si_no("¿Es un PR (rama de migración)?", default_no=True):
                rama_pr = preguntar(
                    "Rama del PR (ej 17.0-mig-web_dark_theme)", "").strip()
                if not rama_pr:
                    print("  Sin rama, uso la automática.")
            mostrar_y_elegir(org_desde_url(url), repo, url, True,
                             rama=rama_pr or "")
            otra = preguntar("¿Agregar otro repo?", "no", ["si", "no"])
            if otra != "si":
                break
            continue
        repos = [e["repo"] for e in catalogo.get(org, [])]
        print(f"\n-- Repos {org} disponibles --")
        for i, e in enumerate(catalogo.get(org, []), 1):
            print(f"  {i:2}) {e['repo']:28} {e.get('desc','')}")
        if len(repos) == 1:
            # Un solo repo en el catálogo: ir directo a sus módulos sin preguntar
            repo = repos[0]
            print(f"  (único repo: {repo}, listando módulos...)")
            url = next(
                (e["url"] for e in catalogo.get(org, []) if e["repo"] == repo),
                f"https://github.com/{KNOWN_ORGS.get(org, org)}/{repo}",
            )
            mostrar_y_elegir(org, repo, url, False)
            otra = preguntar("¿Agregar otro repo?", "no", ["si", "no"])
            if otra != "si":
                break
            continue
        # Checklist multi-repo primero, fallback a texto
        sel_repos = None
        try:
            from .tui import checklist
            sel_repos = checklist(f"Elige repos de {org} ({len(repos)})", repos)
        except Exception:  # noqa: BLE001
            sel_repos = None
        if sel_repos is not None:
            if not sel_repos:
                continue
            for repo in sel_repos:
                if repo not in repos:
                    print(f"  ⚠ '{repo}' no está en el catálogo, omitido.")
                    continue
                url = next(
                    (e["url"] for e in catalogo.get(org, []) if e["repo"] == repo),
                    f"https://github.com/{KNOWN_ORGS.get(org, org)}/{repo}",
                )
                mostrar_y_elegir(org, repo, url, False)
            otra = preguntar("¿Agregar otro origen?", "no", ["si", "no"])
            if otra != "si":
                break
            continue
        print(
            "  (número, nombre u otro repo del org... o pega la URL completa https://github.com/...)"
        )
        repo_raw = preguntar("Repo", "").strip()
        if not repo_raw or repo_raw == "listo":
            break
        if es_url(repo_raw):
            # URL pegada directo: rama y módulos automáticos igual que 'otro'
            url = repo_raw
            repo = url.rstrip("/").split("/")[-1].removesuffix(".git").split(":")[-1]
            mostrar_y_elegir(org_desde_url(url), repo, url, True)
        else:
            if repo_raw.isdigit() and 1 <= int(repo_raw) <= len(repos):
                repo = repos[int(repo_raw) - 1]
            else:
                repo = repo_raw
            # Resolver URL
            url = next(
                (e["url"] for e in catalogo.get(org, []) if e["repo"] == repo),
                f"https://github.com/{KNOWN_ORGS.get(org, org)}/{repo}",
            )
            mostrar_y_elegir(org, repo, url, False)
        otra = preguntar("¿Agregar otro repo?", "no", ["si", "no"])
        if otra != "si":
            break


def aplicar_localizacion(salida: Path, version: str, perfil_key: str,
                         ofrecer_aplicar: bool = True):
    """Instala el bundle del perfil + guarda addons/localizacion.json. Devuelve perfil.

    Con ofrecer_aplicar (y tty) pregunta si correr sync ahora (deps + Dockerfile
    con extras de localización + rebuild). El crear pasa False: sigue su flujo.
    """
    catalogo_loc = cargar_localizaciones()
    if perfil_key not in catalogo_loc:
        sys.exit(
            f"Localización desconocida: {perfil_key} (opciones: "
            f"{', '.join(k for k in catalogo_loc if not k.startswith('_'))})"
        )
    perf = catalogo_loc[perfil_key]
    print(f"\nLocalización {perf.get('nombre', perfil_key)} (rama {version}.0).")
    if perf.get("notas"):
        print(f"  Nota: {perf['notas']}")
    for e in perf.get("bundle", []):
        instalar_addon(
            salida,
            e.get("org", "oca"),
            e["repo"],
            e.get("modules", []),
            version,
            e.get("url", ""),
        )
    # Requirements que trae EL REPO descargado (varía por rama/version):
    # se guardan tal cual y se fusionan al generar el Dockerfile.
    repos = load_repos(salida)
    repo_reqs = []
    for e in perf.get("bundle", []):
        ent = next((r for r in repos if r.get("repo") == e["repo"]), None)
        if not ent:
            continue
        rf = Path(salida) / ent.get("path", "") / "requirements.txt"
        if not rf.exists():
            continue
        n = 0
        for line in rf.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and s not in repo_reqs:
                repo_reqs.append(s)
                n += 1
        if n:
            print(f"  + requirements de {e['repo']}@{version}.0 ({n} líneas).")
    (salida / "addons" / "localizacion.json").write_text(
        json.dumps(
            {
                "perfil": perfil_key,
                "pip_extra": perf.get("pip_extra", []),
                "pip_exclude": perf.get("pip_exclude", []),
                "repo_requirements": repo_reqs,
                "apt": perf.get("apt", []),
                "seclevel": bool(perf.get("seclevel")),
                "pyafipws_cache": bool(perf.get("pyafipws_cache")),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print("  ✓ addons/localizacion.json guardado (apt/SECLEVEL/cache van al Dockerfile).")
    script_params = _escribir_parametros_ar(salida)
    print(f"  ✓ {script_params.name} generado (crea parámetros AR si no existen).")
    print("  → AFIP arranca en homologación (afip.ws.env.type): pasalo a `production`")
    print("    cuando factures de verdad (parametros_ar.sh / parámetros de la compañía).")
    if ofrecer_aplicar and es_interactivo():
        from types import SimpleNamespace

        if ask_si_no(
            "¿Aplicar ahora? (sync: deps + Dockerfile + rebuild)", default_no=False
        ):
            run_sync(
                SimpleNamespace(
                    bundle="",
                    branch="",
                    odoo="",
                    yes=False,
                    no_deploy=False,
                    skip_install=True,
                    proyecto=str(Path(salida).resolve()),
                )
            )
            _ofrecer_fijar_parametros(salida)
        else:
            print("\nSigue con: opción 2 (sync) para Dockerfile + rebuild.")
            print("  Parámetros AR cuando la BD exista: ./scripts/parametros_ar.sh <bd>")
    return perfil_key


def escanear_externas(proyecto):
    """Escanea external_dependencies (manifests + requirements) y escribe requirements-odoo.txt.

    Imprime el reporte humano. Devuelve dict {python, bin, por_modulo}.
    """
    import re

    proyecto = Path(proyecto)
    repos = load_repos(proyecto)
    addons_dir = proyecto / "addons"
    mod_dirs = {}
    for r in repos:
        base = proyecto / r.get("path", "")
        for m in r.get("modules", []):
            d = base / m
            if d.is_dir():
                mod_dirs[m] = d
    for p in addons_dir.iterdir():
        if p.name in (
            "oca",
            "adhoc",
            "cybrosys",
            "mates",
            "codize",
            "custom",
            "extras",
            "repos.json",
        ):
            continue
        if p.is_symlink():
            real = p.resolve() if p.exists() else None
            if real and real.is_dir():
                mod_dirs.setdefault(p.name, real)
        elif p.is_dir():
            mod_dirs.setdefault(p.name, p)
    for sub in ("custom", "extras"):
        d = addons_dir / sub
        if d.is_dir():
            for name, path in iterar_modulos(d):
                mod_dirs.setdefault(name, path)
    py_deps, bin_deps, por_modulo = set(), set(), {}
    mod_requirements = []
    for mod, path in sorted(mod_dirs.items()):
        man = leer_manifest(path)
        ext = man.get("external_dependencies", {}) or {}
        py = ext.get("python", []) or []
        bn = ext.get("bin", []) or []
        if py or bn:
            por_modulo[mod] = {"python": list(py), "bin": list(bn)}
        py_deps.update(py)
        bin_deps.update(bn)
        rf = path / "requirements.txt"
        if rf.exists():
            for line in rf.read_text().splitlines():
                s = line.strip()
                if s and not s.startswith("#") and s not in mod_requirements:
                    mod_requirements.append(s)
    req_hints = {}
    req_lines = []
    for r in repos:
        rf = proyecto / r["path"] / "requirements.txt"
        if rf.exists():
            for line in rf.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                req_lines.append(line)
                base = re.split(r"[=<>;\s\[]", line, 1)[0].strip().lower()
                if base and "://" not in base:
                    req_hints.setdefault(base, line)
    ALIASES = {"openssl": "pyopenssl"}

    def hint_para(dep: str):
        key = dep.strip().lower()
        if key in req_hints:
            return req_hints[key]
        key = ALIASES.get(key, key)
        if key in req_hints:
            return req_hints[key]
        for line in req_lines:
            if key and key in line.lower():
                return line
        return dep.strip()

    out_reqs = [normalizar_req(l) for l in mod_requirements]
    for dep in sorted(py_deps, key=str.lower):
        pinned = normalizar_req(hint_para(dep))
        if pinned not in out_reqs:
            out_reqs.append(pinned)
    if any("pyafipws" in l.lower() for l in out_reqs):
        for i, l in enumerate(out_reqs):
            if "pysimplesoap" in l.lower() and "stable_py3k" in l:
                out_reqs[i] = "pysimplesoap==1.8.22"
                print(
                    "  (quirk AR: stable_py3k->pysimplesoap==1.8.22 para pyafipws>=3)"
                )
                break
    out_reqs, _m2 = quitar_m2crypto(out_reqs)
    if _m2:
        print(
            "  (M2Crypto fuera del pip: va por apt python3-m2crypto;"
            " la localización AR lo pone en el Dockerfile)"
        )
    for _conf in detectar_conflictos(out_reqs):
        print(f"  ⚠ Conflicto de versiones: {_conf} (el build fallará en pip;"
              " fija un pin común)")
    req_file = proyecto / "requirements-odoo.txt"
    if out_reqs:
        req_file.write_text("\n".join(out_reqs) + "\n", encoding="utf-8")
    else:
        if req_file.exists():
            req_file.unlink()
    print(f"Módulos analizados: {len(mod_dirs)}")
    if por_modulo:
        print("\nDependencias por módulo:")
        for mod, d in por_modulo.items():
            print(f"  {mod}: python={d['python'] or '-'} bin={d['bin'] or '-'}")
    else:
        print("Sin external_dependencies en manifests.")
    if py_deps:
        print(f"\nPython ({len(py_deps)}): {' '.join(sorted(py_deps))}")
        print(f"→ generado {req_file.name}")
    else:
        print("\nSin dependencias Python.")
    if bin_deps:
        print(f"\nBinarios sistema ({len(bin_deps)}): {' '.join(sorted(bin_deps))}")
        print("  → instalar vía apt en Dockerfile (ver sugerencia).")
    if req_hints and not py_deps:
        print(
            f"\nNota: los repos traen requirements.txt ({len(req_hints)} líneas) "
            "pero ningún módulo descargado las declara. Revisa si las necesitas."
        )
    return {
        "python": sorted(py_deps),
        "bin": sorted(bin_deps),
        "por_modulo": por_modulo,
    }


def paso_dependencias(salida: Path, mapping: dict, auto=False, puerto=None):
    """Detecta external_dependencies, genera requirements-odoo.txt + Dockerfile si hace falta.

    Si hay Dockerfile para generar y puerto dado (interactivo, no auto): UNA sola
    pregunta (Dockerfile + rebuild) y devuelve True para saltear paso_despliegue.
    En auto/sin puerto: comportamiento clásico y devuelve False.
    """
    print("\n-- Resolviendo dependencias externas de los módulos --")
    data = escanear_externas(salida)
    py, bn = data.get("python", []), data.get("bin", [])
    if not py and not bn:
        print("Sin dependencias externas. Nada que hacer.")
        return False
    if bn:
        print(f"⚠ Binarios sistema requeridos: {' '.join(bn)}")
        print("  Edita el Dockerfile generado (línea apt-get) para instalarlos.")

    def _generar_dockerfile():
        # extras de localización (pip/apt/seclevel/cache) desde addons/localizacion.json
        bloques = bloques_localizacion(salida)
        m2 = dict(mapping)
        m2["APT_PKGS"] = bloques["APT_PKGS"]
        m2["SECPY_BLOCK"] = bloques["SECPY_BLOCK"]
        (salida / "Dockerfile").write_text(
            render(cargar_template("Dockerfile.tpl"), m2), encoding="utf-8"
        )
        (salida / ".dockerignore").write_text(
            cargar_template("dockerignore.tpl"), encoding="utf-8"
        )
        parchear_compose_a_build(salida, mapping)
        print("  ✓ Dockerfile + .dockerignore generados, compose pasado a build.")

    def _desplegar_ahora():
        print(f"\nDesplegando en {salida} ...")
        print(
            "  (el primer build tarda varios minutos: pull Odoo + pip. Verás el progreso abajo)"
        )
        r = subprocess.run(
            ["docker", "compose", "up", "-d", "--build"], cwd=str(salida)
        )
        if r.returncode == 0:
            puerto_loc = mapping.get("ODOO_PORT", "?")
            print(f"✓ Desplegado. Abrir http://localhost:{puerto_loc}")
            print(f"  Logs: cd {salida} && docker compose logs -f odoo")
        else:
            print("⚠ Falló el despliegue.")
            print(
                "  Si dice 'port is already allocated': docker ps --format 'table {{.Names}}\\t{{.Ports}}'"
            )
            print(
                "  Y cambia ODOO_PORT / ODOO_GEVENT_PORT en .env + docker-compose.yml."
            )
            print("  Si no, revisa con: docker compose logs -f")

    if py:
        # UNA sola pregunta (interactivo con puerto): Dockerfile + rebuild juntos
        if puerto is not None and not auto and es_interactivo():
            if (
                preguntar(
                    "¿Generar Dockerfile y reconstruir ahora? (up -d --build)",
                    "si",
                    ["si", "no"],
                )
                == "si"
            ):
                _generar_dockerfile()
                _desplegar_ahora()
            else:
                print(
                    f"\nPara hacerlo luego: cd {salida} && docker compose up -d --build"
                )
            return True
        if auto or (
            es_interactivo()
            and preguntar(
                "¿Generar Dockerfile con estas dependencias Python?", "si", ["si", "no"]
            )
            == "si"
        ):
            _generar_dockerfile()
        else:
            print(
                "  requirements-odoo.txt generado pero sin Dockerfile (instálalas a mano)."
            )
        return False


def paso_despliegue(salida: Path, puerto: int, auto=False):
    """Pregunta final: ¿desplegar? Ejecuta docker compose up -d --build."""
    if auto:
        deploy = True
    elif not es_interactivo():
        print(f"\nPara desplegar: cd {salida} && docker compose up -d --build")
        return
    else:
        deploy = (
            preguntar(
                "¿Desplegar ahora? (docker compose up -d --build)", "no", ["si", "no"]
            )
            == "si"
        )
    if not deploy:
        print(f"\nPara desplegar luego: cd {salida} && docker compose up -d --build")
        return
    print(f"\nDesplegando en {salida} ...")
    print(
        "  (el primer build tarda varios minutos: pull Odoo + pip. Verás el progreso abajo)"
    )
    # Sin capturar salida: el progreso se ve EN VIVO (antes parecía colgado)
    r = subprocess.run(["docker", "compose", "up", "-d", "--build"], cwd=str(salida))
    if r.returncode == 0:
        print(f"✓ Desplegado. Abrir http://localhost:{puerto}")
        print(f"  Logs: cd {salida} && docker compose logs -f odoo")
    else:
        print("⚠ Falló el despliegue.")
        print(
            "  Si dice 'port is already allocated': docker ps --format 'table {{.Names}}\\t{{.Ports}}'"
        )
        print("  Y cambia ODOO_PORT / ODOO_GEVENT_PORT en .env + docker-compose.yml.")
        print("  Si no, revisa con: docker compose logs -f")


def leer_env_proyecto(salida: Path) -> dict:

    envf = salida / ".env"
    if not envf.exists():
        sys.exit(f"{salida} no parece un proyecto (sin .env).")
    d = {}
    for line in envf.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            d[k.strip()] = v.strip()
    return d


def es_prod(proj: Path) -> bool:
    """Prod según .env ENTORNO; legacy: tiene scripts/backup.sh."""
    try:
        for line in (proj / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("ENTORNO="):
                return line.split("=", 1)[1].strip() == "produccion"
    except OSError:
        pass
    return (proj / "scripts" / "backup.sh").exists()


def exigir_prod(proj: Path, que: str) -> bool:

    if es_prod(proj):
        return True
    print(f"  ⚠ {que} es solo de producción (este proyecto es desarrollo).")
    return False


def _certonly_cmd(email: str, dominio: str, staging: bool) -> list:
    """Comando certonly webroot para el dominio + www."""
    cmd = ["docker", "compose", "run", "--rm", "certbot", "certonly",
           "--webroot", "-w", "/var/www/certbot",
           "--email", email, "--agree-tos", "--no-eff-email",
           "-d", dominio, "-d", f"www.{dominio}"]
    if staging:
        cmd.append("--staging")
    return cmd


def _activar_https(salida: Path, dominio: str, email: str, staging: bool) -> bool:
    """Obtiene el cert (dominio + www) y deja nginx.conf con la estructura HTTPS.

    Levanta nginx (día 1 HTTP), corre certonly, reemplaza nginx.conf por
    nginx-https.conf.tpl y recarga. Devuelve True si quedó activo.
    """
    salida = Path(salida).resolve()
    print(seccion("\n== Activando HTTPS =="))
    r = subprocess.run(["docker", "compose", "up", "-d", "nginx"], cwd=str(salida))
    if r.returncode != 0:
        print("  ⚠ No pude levantar nginx. Hacelo a mano y reintenta.")
        return False
    print(f"  Obteniendo certificado para {dominio} + www.{dominio} ...")
    r = subprocess.run(_certonly_cmd(email, dominio, staging), cwd=str(salida))
    if r.returncode != 0:
        print("  ⚠ certbot falló (¿DNS apunta al VPS? ¿puerto 80 abierto?).")
        print("  Queda el HTTP del día 1; reintenta cuando el DNS resuelva.")
        return False
    (salida / "nginx" / "nginx.conf").write_text(
        render(cargar_template("nginx-https.conf.tpl"), {
            "PROYECTO": salida.name,
            "DOMINIO": dominio,
            "ODOO_HOST": "odoo",
        }), encoding="utf-8")
    r = subprocess.run(["docker", "compose", "exec", "nginx", "nginx", "-s", "reload"],
                       cwd=str(salida))
    if r.returncode != 0:
        print("  ⚠ No pude recargar nginx; reinícialo a mano:")
        print(f"  cd {salida} && docker compose restart nginx")
        return False
    print(f"  ✓ HTTPS activo: https://{dominio} (www redirige al apex).")
    return True


def _elegir_modo_web(args, salida: Path) -> bool:
    """True = proxy central, False = nginx propio. Nunca ambiguo.

    Flags mandan; si no, en no-interactivo decide si hay proxy inicializado
    (sin proxy, clásico para no cambiar nada); en interactivo se pregunta.
    """
    if getattr(args, "standalone", False):
        return False
    if getattr(args, "proxy", False):
        return True
    from .compose import PROXY_PROJECT
    from .core import projects_home
    hay_proxy = (projects_home() / PROXY_PROJECT / "docker-compose.yml").exists()
    if getattr(args, "no_input", False) or not es_interactivo():
        return hay_proxy
    modo = ask_opcion(
        "¿Proxy central (multi-subdominio) o nginx propio del proyecto?",
        ["Proxy central (recomendado si hay más de un proyecto)",
         "Nginx propio (standalone, un solo HTTPS por host)"],
        "Proxy central (recomendado si hay más de un proyecto)" if hay_proxy
        else "Nginx propio (standalone, un solo HTTPS por host)")
    return modo.startswith("Proxy")


def _activar_https_proxy(salida: Path, proxy_root: Path, dominio: str,
                         email: str, staging: bool) -> bool:
    """Cert central + site HTTPS en el proxy. Requiere sitio odoo levantado.

    Si ya hay cert válido y no es staging, lo conserva (no re-emite).
    Devuelve True si quedó activo (día 1 intacto si certbot falla).
    """
    salida = Path(salida).resolve()
    proxy_root = Path(proxy_root).resolve()
    odoo_host = f"{salida.name.lower()}-odoo"
    print(seccion("\n== Activando HTTPS en el proxy =="))
    live = proxy_root / "letsencrypt" / "live" / dominio / "fullchain.pem"
    if live.exists() and not staging:
        print(f"  Cert válido existente para {dominio}: se conserva (sin re-emitir).")
    else:
        print(f"  Obteniendo certificado para {dominio} + www.{dominio} ...")
        r = subprocess.run(_certonly_cmd(email, dominio, staging), cwd=str(proxy_root))
        if r.returncode != 0:
            print("  ⚠ certbot falló (¿DNS apunta al VPS? ¿puerto 80 abierto?).")
            print("  Queda el HTTP del día 1; reintenta cuando el DNS resuelva.")
            return False
    sitio = proxy_root / "conf.d" / f"{dominio}.conf"
    sitio.write_text(render(cargar_template("proxy-site-https.conf.tpl"), {
        "PROYECTO": salida.name,
        "DOMINIO": dominio,
        "ODOO_HOST": odoo_host,
    }), encoding="utf-8")
    r = subprocess.run(["docker", "compose", "exec", "nginx", "nginx", "-t"],
                       cwd=str(proxy_root))
    if r.returncode != 0:
        print("  ⚠ nginx -t falló en el proxy con el site nuevo (revisá el dominio).")
        return False
    r = subprocess.run(["docker", "compose", "exec", "nginx", "nginx", "-s", "reload"],
                       cwd=str(proxy_root))
    if r.returncode != 0:
        print("  ⚠ No pude recargar el proxy; reinícialo a mano:")
        print(f"  cd {proxy_root} && docker compose restart nginx")
        return False
    print(f"  ✓ HTTPS activo: https://{dominio} (www redirige al apex).")
    print(f"  Renovar todo (cron semanal en host: 0 3 * * 0): cd {proxy_root} && "
          "docker compose run --rm certbot renew && "
          "docker compose exec nginx nginx -s reload")
    return True


def modo_configurar_web_proxy(args, salida, dominio: str, email: str, staging: bool) -> None:
    """Web vía proxy central: parchea sitio, site día 1, cert central, HTTPS.

    Falla limpio (sys.exit) sin dejar nada a medias: primero lo reversible.
    """
    from .compose import PROXY_PROJECT, asegurar_proxy_mode, parchear_compose_a_proxy
    from .core import projects_home

    salida = Path(salida).resolve()
    proxy_root = (projects_home() / PROXY_PROJECT).resolve()
    if not (proxy_root / "docker-compose.yml").exists():
        if es_interactivo() and not getattr(args, "no_input", False):
            if ask_si_no(f"¿Inicializar proxy central ahora? ({proxy_root} + red omc-proxy)", True):
                run_proxy_init()
            else:
                sys.exit(f"No hay proxy central en {proxy_root} (corre `omc proxy init` primero).")
        else:
            sys.exit(f"No hay proxy central en {proxy_root} (corre `omc proxy init` primero). "
                     f"Verificá con: ls {proxy_root}/docker-compose.yml)")
    odoo_host = f"{salida.name.lower()}-odoo"
    # 1) proxy arriba (si 80/443 los tiene otro, falla acá con mensaje claro)
    r = subprocess.run(["docker", "compose", "up", "-d"], cwd=str(proxy_root))
    if r.returncode != 0:
        sys.exit("No pude levantar el proxy (¿puerto 80/443 ocupado por traefik u otro "
                 "nginx?). Revisá con: docker ps --format '{{.Names}} {{.Ports}}'")
    # 2) parchear sitio (falla limpio si tiene nginx local) + proxy_mode
    cambios = parchear_compose_a_proxy(salida, salida.name)["cambios"]
    if cambios:
        print(f"  ✓ compose del sitio: {', '.join(cambios)}.")
    if asegurar_proxy_mode(salida):
        print("  ✓ proxy_mode = True en odoo.conf.")
    # 3) sitio odoo arriba (el proxy debe resolver el upstream al recargar)
    r = subprocess.run(["docker", "compose", "up", "-d"], cwd=str(salida))
    if r.returncode != 0:
        sys.exit(f"No pude levantar {salida} (revisá su compose).")
    # 4) site día 1 + gzip si falta + reload validado
    confd = proxy_root / "conf.d"
    confd.mkdir(exist_ok=True)
    if not (confd / "gzip.conf").exists():
        (confd / "gzip.conf").write_text(
            render(cargar_template("nginx-gzip.conf.tpl"), {"PROYECTO": PROXY_PROJECT}),
            encoding="utf-8")
    sitio = confd / f"{dominio}.conf"
    sitio.write_text(render(cargar_template("proxy-site.conf.tpl"), {
        "PROYECTO": salida.name, "DOMINIO": dominio, "ODOO_HOST": odoo_host,
    }), encoding="utf-8")
    print(f"  ✓ site día 1 en proxy: conf.d/{dominio}.conf.")
    r = subprocess.run(["docker", "compose", "exec", "nginx", "nginx", "-t"],
                       cwd=str(proxy_root))
    if r.returncode != 0:
        sys.exit("nginx -t falló en el proxy con el site nuevo (revisá el dominio).")
    r = subprocess.run(["docker", "compose", "exec", "nginx", "nginx", "-s", "reload"],
                       cwd=str(proxy_root))
    if r.returncode != 0:
        sys.exit(f"nginx -t ok pero reload falló; recargá a mano: cd {proxy_root} "
                 "&& docker compose restart nginx")
    # 5) cert central + HTTPS
    if _activar_https_proxy(salida, proxy_root, dominio, email, staging):
        print(f"=== Web por proxy para https://{dominio} (staging={staging}) ===")
    # 6) persistir en .env del sitio
    envf = salida / ".env"
    env_txt = envf.read_text(encoding="utf-8") if envf.exists() else ""
    for k, v in (("DOMINIO", dominio), ("CERTBOT_EMAIL", email)):
        import re as _re
        env_txt = (_re.sub(rf"^{k}=.*$", f"{k}={v}", env_txt, flags=_re.M)
                   if f"\n{k}=" in "\n" + env_txt
                   else env_txt.rstrip("\n") + f"\n{k}={v}\n")
    envf.write_text(env_txt, encoding="utf-8")


def modo_configurar_web(args):

    salida = Path(args.proyecto).resolve() if args.proyecto else Path.cwd()
    if not (salida / "docker-compose.yml").exists():
        sys.exit(f"{salida} no parece un proyecto (sin docker-compose.yml).")
    env = leer_env_proyecto(salida)
    if "ODOO_VERSION" not in env or "ODOO_IMAGE" not in env:
        sys.exit(f"{salida}/.env incompleto (falta ODOO_VERSION/ODOO_IMAGE).")
    dominio = args.dominio or ""
    email = args.email or ""
    staging = args.staging
    if not args.no_input and es_interactivo() and (not dominio or not email):
        dominio = dominio or preguntar("Dominio (ej odoo.midominio.com)", "").strip()
        if not dominio:
            sys.exit("Sin dominio no hay certbot. Abortado.")
        email = email or preguntar("Email para Let's Encrypt", "").strip()
        if not email:
            sys.exit("Sin email Let's Encrypt no emite. Abortado.")
        if (
            not staging
            and preguntar("¿Certificado de PRUEBA staging? (ENTER=no=real trusted; si=solo para no quemar límite)",
                          "no", ["si", "no"])
            == "si"
        ):
            staging = True
    if not dominio or not email:
        sys.exit("Faltan --dominio y/o --email (o corre interactivo).")
    if _elegir_modo_web(args, salida):
        print(f"  Modo: proxy central (site en <proyectos>/proxy/conf.d/{dominio}.conf, "
              f"cert central, staging={staging}).")
        modo_configurar_web_proxy(args, salida, dominio, email, staging)
        return
    print("  Modo: nginx propio (standalone, un solo HTTPS por host).")
    mapping = {
        "PROYECTO": salida.name,
        "ODOO_VERSION": env["ODOO_VERSION"],
        "DOMINIO": dominio,
        "ODOO_HOST": "odoo",
        "CERTBOT_EMAIL": email,
        "CERTBOT_STAGING": " --staging" if staging else "",
    }
    (salida / "nginx").mkdir(exist_ok=True)
    (salida / "letsencrypt").mkdir(exist_ok=True)
    (salida / "certbot-www").mkdir(exist_ok=True)
    (salida / "nginx" / "nginx.conf").write_text(
        render(cargar_template("nginx.conf.tpl"), mapping), encoding="utf-8"
    )
    (salida / "nginx" / "gzip.conf").write_text(
        render(cargar_template("nginx-gzip.conf.tpl"), mapping), encoding="utf-8"
    )
    print("  ✓ nginx/nginx.conf (día 1 HTTP) + nginx/gzip.conf generados.")
    f = salida / "docker-compose.yml"
    txt = f.read_text(encoding="utf-8")
    if "  nginx:" not in txt:
        # odoo directo -> interno; agregar bloque nginx+certbot antes de volumes:
        puerto = env.get("ODOO_PORT", "8069")
        txt = txt.replace(
            f'    ports:\n      - "{puerto}:8069"\n', '    expose:\n      - "8069"\n', 1
        )
        bloque = render(cargar_template("compose-nginx-block.yml.tpl"), mapping)
        txt = txt.replace("\nvolumes:", "\n" + bloque + "volumes:", 1)
        f.write_text(txt, encoding="utf-8")
        print("  ✓ servicios nginx+certbot agregados; odoo pasa a expose:8069.")
    else:
        # nginx ya existía: actualizar sitio a odoo.conf + montar gzip.conf si faltan
        if "conf.d/default.conf" in txt:
            txt = txt.replace("conf.d/default.conf", "conf.d/odoo.conf")
        if "gzip.conf" not in txt:
            txt = txt.replace(
                "      - ./nginx/nginx.conf:/etc/nginx/conf.d/odoo.conf:ro\n",
                "      - ./nginx/nginx.conf:/etc/nginx/conf.d/odoo.conf:ro\n"
                "      - ./nginx/gzip.conf:/etc/nginx/conf.d/gzip.conf:ro\n",
                1)
        f.write_text(txt, encoding="utf-8")
        print("  (nginx ya existía en el compose; conf actualizada: sitio odoo.conf + gzip)")
    # proxy_mode en odoo.conf (imprescindible detrás de nginx)
    from .compose import asegurar_proxy_mode
    if asegurar_proxy_mode(salida):
        print("  ✓ proxy_mode = True en odoo.conf.")
    # persistir en .env
    env_txt = (salida / ".env").read_text(encoding="utf-8")
    for k, v in (("DOMINIO", dominio), ("CERTBOT_EMAIL", email)):
        import re as _re

        env_txt = (
            _re.sub(rf"^{k}=.*$", f"{k}={v}", env_txt, flags=_re.M)
            if f"\n{k}=" in "\n" + env_txt
            else env_txt.rstrip("\n") + f"\n{k}={v}\n"
        )
    (salida / ".env").write_text(env_txt, encoding="utf-8")
    print(f"=== Web configurada para https://{dominio} (staging={staging}) ===")
    if not getattr(args, "no_input", False) and es_interactivo() and ask_si_no(
            "¿Obtener certificado y activar HTTPS ahora? (levanta nginx, corre "
            "certonly, recarga)", default_no=False):
        _activar_https(salida, dominio, email, staging)
        return
    print(f"  cd {salida} && docker compose up -d")
    print("  " + " ".join(_certonly_cmd(email, dominio, staging)))
    print(
        "  Luego se reemplaza nginx/nginx.conf por la estructura HTTPS y se recarga:"
        f" cd {salida} && docker compose exec nginx nginx -s reload"
    )


def modo_configurar_rclone(args):

    salida = Path(args.proyecto).resolve() if args.proyecto else Path.cwd()
    if not (salida / "docker-compose.yml").exists():
        sys.exit(f"{salida} no parece un proyecto (sin docker-compose.yml).")
    # Servicio rclone (perfil backup) si el compose es anterior
    ctxt = (salida / "docker-compose.yml").read_text(encoding="utf-8")
    if "\n  rclone:" not in ctxt:
        bloque = render(
            cargar_template("compose-rclone-block.yml.tpl"),
            {"PROYECTO": salida.name, "RCLONE_REMOTE": args.rclone_remote or "gdrive"},
        )
        ctxt = ctxt.replace("\nvolumes:", "\n" + bloque + "volumes:", 1)
        (salida / "docker-compose.yml").write_text(ctxt, encoding="utf-8")
        print("  ✓ servicio rclone agregado al compose.")
    remote = args.rclone_remote or ""
    if not args.no_input and es_interactivo() and not remote:
        remote = (
            preguntar("Nombre del remote rclone (default gdrive)", "gdrive") or "gdrive"
        )
    remote = remote or "gdrive"
    (salida / "scripts").mkdir(exist_ok=True)
    rconf = salida / "scripts" / "rclone.conf"
    if not rconf.exists():
        try:
            tpl = template_text("rclone.conf.tpl")
        except FileNotFoundError:
            tpl = "[REMOTE]\ntype = drive\n"
        rconf.write_text(
            tpl.replace("{{RCLONE_REMOTE}}", remote).replace(
                "{{PROYECTO}}", salida.name
            ),
            encoding="utf-8",
        )
        print(f"  ✓ {rconf} creado (complétalo con rclone config o a mano).")
    import shutil as _sh

    # Sin nada que instalar en host: se configura dentro del servicio rclone del compose
    if not args.no_input and es_interactivo():
        if (
            preguntar(
                "¿Ejecutar 'rclone config' ahora para conectar Google Drive?",
                "si",
                ["si", "no"],
            )
            == "si"
        ):
            if _sh.which("rclone") is None:
                print("  (uso el servicio rclone del compose, sin instalar nada)")
            subprocess.run(
                [
                    "docker",
                    "compose",
                    "--profile",
                    "backup",
                    "run",
                    "--rm",
                    "rclone",
                    "config",
                ],
                cwd=str(salida),
            )
            print(f"  ✓ Config guardada en {rconf} (montada por el servicio).")
    print(f"  Verificando acceso al remote '{remote}' ...")
    t = subprocess.run(
        [
            "docker",
            "compose",
            "--profile",
            "backup",
            "run",
            "--rm",
            "rclone",
            "lsd",
            f"{remote}:",
        ],
        cwd=str(salida),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=90,
    )
    if t.returncode == 0:
        print(
            f"  ✓ Remote '{remote}' OK. Los backups subirán a {remote}:{salida.name}/"
        )
    else:
        print(f"  ⚠ No se pudo listar '{remote}:'. Revisa el token en {rconf}.")
        print((t.stdout or "")[-1500:])
    # persistir remote en .env
    import re as _re2

    envf = salida / ".env"
    if envf.exists():
        etxt = envf.read_text(encoding="utf-8")
        etxt = (
            _re2.sub(
                r"^RCLONE_REMOTE=.*$", f"RCLONE_REMOTE={remote}", etxt, flags=_re2.M
            )
            if "\nRCLONE_REMOTE=" in "\n" + etxt
            else etxt.rstrip("\n") + f"\nRCLONE_REMOTE={remote}\n"
        )
        envf.write_text(etxt, encoding="utf-8")


def elegir_repo_guiado(proyecto: Path, dep: str, branch: str, cat: dict) -> bool:
    """Opción 1: OCA/AdHoc del catálogo u Otro por URL; lista, filtra y descarga. True si trajo algo."""
    o = ask_opcion(
        f"¿Dónde está {dep}?",
        ["OCA", "Ad Hoc", "Otro (pego el enlace)"],
        "Otro (pego el enlace)",
    )
    if o in ("OCA", "Ad Hoc"):
        org = "oca" if o == "OCA" else "adhoc"
        entries = [e for e in cat.get(org, []) if isinstance(e, dict)]
        print(f"\n-- Repos {org.upper()} --")
        for i, e in enumerate(entries, 1):
            marca = (
                "  <-- parece ser este"
                if e["repo"].replace("-", "_") in dep or dep in e["repo"]
                else ""
            )
            print(f"  {i:2}) {e['repo']}{marca}")
        sel = ask_texto("Repo (número o nombre; vacío=salir)", "")
        if not sel:
            return False
        if sel.isdigit() and 1 <= int(sel) <= len(entries):
            e = entries[int(sel) - 1]
        else:
            e = next((x for x in entries if x["repo"] == sel), None)
            if not e:
                print("  No está en el catálogo.")
                return False
        org2, repo, url = org, e["repo"], e["url"]
    else:
        url = ask_texto("Enlace GitHub del repo", "")
        if not url:
            return False
        org2, repo, url = resolve_repo("custom", url, "", cat)
    print(f"Listando {repo}@{branch} ...")
    try:
        dirs, unico, _ramas = list_remote_topdirs(url, branch)
    except SystemExit:
        return False
    if dirs is None:
        return False
    if unico:
        print("  Es un solo módulo; se descarga entero.")
        add_modules(proyecto, org2, repo, url, branch, [repo])
        return True
    print(f"-- Módulos en {repo}@{branch} ({len(dirs)}) --")
    ordenados = sorted(dirs)
    for i, m in enumerate(ordenados, 1):
        marca = "  <-- buscas este" if m == dep else ""
        print(f"  {i:3}) {m}{marca}")
    raw = ask_texto("Módulos (números, nombres o 'todo'; vacío=solo el buscado)", "")
    if not raw and dep in ordenados:
        elegidos = [dep]
    elif not raw:
        return False
    elif raw.strip().lower() in ("todo", "todos", "all", "*"):
        elegidos = ordenados
    else:
        elegidos, inv = [], []
        for tok in [t.strip() for t in raw.replace(" ", ",").split(",") if t.strip()]:
            if tok.isdigit() and 1 <= int(tok) <= len(ordenados):
                elegidos.append(ordenados[int(tok) - 1])
            elif tok in ordenados:
                elegidos.append(tok)
            else:
                inv.append(tok)
        for v in inv:
            print(f"  ⚠ '{v}' no existe, omitido.")
        elegidos = sorted(set(elegidos))
        if not elegidos:
            return False
    add_modules(proyecto, org2, repo, url, branch, elegidos)
    return True


def configurar_github_interactivo() -> bool:
    """Pide token + org, valida contra la API y guarda en ~/.config (0600)."""
    cfg = gh_config_leer()
    tok = gh_token()
    print(
        f"Token actual: {'...' + tok[-4:] if tok else '(vacío)'} | Org: {gh_org() or '(vacío)'}"
    )
    nuevo = ask_texto("Nuevo token (vacío = mantener)", "")
    if nuevo:
        cfg["github_token"] = nuevo
    org = ask_texto(
        f"Org/usuario [{cfg.get('github_org', '')}]", cfg.get("github_org", "")
    )
    if org:
        cfg["github_org"] = org
    if not cfg:
        print("  Nada que guardar.")
        return False
    if cfg.get("github_token"):
        login = gh_validar_token(cfg["github_token"])
        if login:
            print(f"  ✓ Token válido (login {login}).")
            if not cfg.get("github_org"):
                # Sin organización: el dueño es tu usuario (vale para clonar tus privados)
                cfg["github_org"] = login
                print(f"  ✓ Org/usuario = {login} (tus repos van como {login}/<repo>).")
        else:
            print("  ⚠ No se pudo validar. Se guarda igual.")
    p = gh_config_guardar(cfg)
    print(f"  ✓ Guardado en {p}.")
    return True


def run_check_deps(args):
    import re

    proyecto = find_proyecto(args.proyecto)
    repos = load_repos(proyecto)
    # Módulos efectivos: los de repos.json (vía addons_path) + custom/* + symlinks legacy
    addons_dir = proyecto / "addons"
    mod_dirs = {}
    for r in repos:
        base = proyecto / r.get("path", "")
        for m in r.get("modules", []):
            d = base / m
            if d.is_dir():
                mod_dirs[m] = d
    for p in addons_dir.iterdir():
        if p.name in (
            "oca",
            "adhoc",
            "cybrosys",
            "mates",
            "codize",
            "custom",
            "extras",
            "repos.json",
        ):
            continue
        if p.is_symlink():
            # compat legacy: contarlos mientras existan
            real = p.resolve() if p.exists() else None
            if real and real.is_dir():
                mod_dirs.setdefault(p.name, real)
        elif p.is_dir():
            mod_dirs.setdefault(p.name, p)
    # también custom/* directos (y un nivel adentro: custom/<repo>/<mod>)
    for sub in ("custom", "extras"):
        d = addons_dir / sub
        if d.is_dir():
            for name, path in iterar_modulos(d):
                mod_dirs.setdefault(name, path)
    py_deps, bin_deps, por_modulo = set(), set(), {}
    mod_requirements = (
        []
    )  # líneas de requirements.txt propios de cada módulo (autoritativas)
    for mod, path in sorted(mod_dirs.items()):
        man = leer_manifest(path)
        ext = man.get("external_dependencies", {}) or {}
        py = ext.get("python", []) or []
        bn = ext.get("bin", []) or []
        if py or bn:
            por_modulo[mod] = {"python": list(py), "bin": list(bn)}
        py_deps.update(py)
        bin_deps.update(bn)
        for req_name in ("requirements.txt",):
            rf = path / req_name
            if rf.exists():
                for line in rf.read_text().splitlines():
                    s = line.strip()
                    if s and not s.startswith("#") and s not in mod_requirements:
                        mod_requirements.append(s)
    # requirements.txt de los repos clonados (referencia, puede traer extras)
    # Se indexan por nombre base Y por subcadena (para URLs git como pyafipws@py3k)
    req_hints = {}
    req_lines = []
    for r in repos:
        rf = proyecto / r["path"] / "requirements.txt"
        if rf.exists():
            for line in rf.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                req_lines.append(line)
                base = re.split(r"[=<>;\s\[]", line, 1)[0].strip().lower()
                if base and "://" not in base:
                    req_hints.setdefault(base, line)
    ALIASES = {"openssl": "pyopenssl"}

    def hint_para(dep: str):
        key = dep.strip().lower()
        if key in req_hints:
            return req_hints[key]
        key = ALIASES.get(key, key)
        if key in req_hints:
            return req_hints[key]
        # buscar subcadena en líneas git/url (ej pyafipws en git+https://.../pyafipws.git@py3k)
        for line in req_lines:
            if key and key in line.lower():
                return line
        return dep.strip()

    # Generar requirements-odoo.txt: propios de módulos + manifests pineados, nombres normalizados
    out_reqs = [normalizar_req(l) for l in mod_requirements]
    for dep in sorted(py_deps, key=str.lower):
        pinned = normalizar_req(hint_para(dep))
        if pinned not in out_reqs:
            out_reqs.append(pinned)
    # Quirk pila AFIP AR: pyafipws>=3 exige pysimplesoap==1.8.22 pero la rama
    # stable_py3k trae 1.8.14 (caso requirements de Codize). Se fuerza el pin bueno.
    if any("pyafipws" in l.lower() for l in out_reqs):
        for i, l in enumerate(out_reqs):
            if "pysimplesoap" in l.lower() and "stable_py3k" in l:
                out_reqs[i] = "pysimplesoap==1.8.22"
                print(
                    "  (quirk AR: stable_py3k->pysimplesoap==1.8.22 para pyafipws>=3)"
                )
                break
    out_reqs, _m2 = quitar_m2crypto(out_reqs)
    if _m2:
        print(
            "  (M2Crypto fuera del pip: va por apt python3-m2crypto;"
            " la localización AR lo pone en el Dockerfile)"
        )
    for _conf in detectar_conflictos(out_reqs):
        print(f"  ⚠ Conflicto de versiones: {_conf} (el build fallará en pip;"
              " fija un pin común)")
    req_file = proyecto / "requirements-odoo.txt"
    if out_reqs:
        req_file.write_text("\n".join(out_reqs) + "\n", encoding="utf-8")
    else:
        if req_file.exists():
            req_file.unlink()
    print(f"Módulos analizados: {len(mod_dirs)}")
    if por_modulo:
        print("\nDependencias por módulo:")
        for mod, d in por_modulo.items():
            print(f"  {mod}: python={d['python'] or '-'} bin={d['bin'] or '-'}")
    else:
        print("Sin external_dependencies en manifests.")
    if py_deps:
        print(f"\nPython ({len(py_deps)}): {' '.join(sorted(py_deps))}")
        print(f"→ generado {req_file.name}")
    else:
        print("\nSin dependencias Python.")
    if bin_deps:
        print(f"\nBinarios sistema ({len(bin_deps)}): {' '.join(sorted(bin_deps))}")
        print("  → instalar vía apt en Dockerfile (ver sugerencia).")
    if req_hints and not py_deps:
        print(
            f"\nNota: los repos traen requirements.txt ({len(req_hints)} líneas) "
            "pero ningún módulo descargado las declara. Revisa si las necesitas."
        )
    # Salida máquina para el asistente
    if getattr(args, "json_out", False):
        print(
            json.dumps(
                {
                    "python": sorted(py_deps),
                    "bin": sorted(bin_deps),
                    "por_modulo": por_modulo,
                }
            )
        )


def run_deps(args):
    proyecto = find_proyecto(args.proyecto)
    # Con tty (y sin --yes) se pregunta aunque venga --fix: si no está ni en el
    # catálogo, el usuario puede indicar dónde buscarlo en vez de loopear en vano.
    preguntar = sys.stdin.isatty() and not getattr(args, "yes", False)
    for _ in range(5):  # loop por cadenas (A->B->C)
        avance = False
        reporte, mismo_repo, total = analizar_depends(proyecto)
        if getattr(args, "porcelain", False):
            n = len(mismo_repo) + len(total)
            print("TODO_RESUELTO" if n == 0 else f"PENDIENTES:{n}")
            return
        print(seccion("\n== Dependencias entre módulos =="))
        foco = {
            x.strip()
            for x in (getattr(args, "enfocar", "") or "").split(",")
            if x.strip()
        }
        for mod in sorted(reporte):
            if foco and mod not in foco:
                continue
            det = ", ".join(f"{d}[{e}]" for d, e in reporte[mod])
            print(f"  {mod}: {det or '(sin depends)'}")
        if foco and not [m for m in reporte if m in foco]:
            print("  (los nuevos no declaran depends)")
        if not mismo_repo and not total:
            print("✓ Todo resuelto.")
            return
        if mismo_repo:
            print("\nDisponibles en repos ya clonados (mismo repo, sin descargar):")
            for rp, mods in sorted(mismo_repo.items()):
                print(f"  {rp}: {' '.join(sorted(mods))}")
        if total:
            print("\nFaltantes (ni en disco ni en base confirmada):")
            branch = args.branch or (
                odoo_to_branch(args.odoo) if args.odoo else read_env_branch(proyecto)
            )
            cat = load_catalog()
            sugeridos = {}
            pendientes = []
            for dep in sorted(total):
                hits = (
                    buscar_modulo_en_catalogo(dep, branch, cat, progreso=True)
                    if branch
                    else []
                )
                if hits:
                    org, repo, url = hits[0]
                    print(
                        f"  {dep} -> {org}/{repo} "
                        f"(add {repo} {dep} --org {org}"
                        + (
                            f" --url {url}"
                            if org.lower()
                            not in ("oca", "adhoc", "cybrosys", "mates", "codize")
                            else ""
                        )
                        + ")"
                    )
                    if len(hits) > 1:
                        print(
                            f"    (también en: {', '.join(f'{o}/{r}' for o, r, _ in hits[1:3])})"
                        )
                    sugeridos[dep] = hits[0]
                else:
                    print(f"  {dep} (no está en el catálogo)")
                    pendientes.append(dep)
            if pendientes and preguntar:
                for dep in pendientes:
                    como = ask_opcion(
                        f"{dep} no aparece. ¿Cómo lo resolvemos?",
                        [
                            "Indico dónde está (OCA / Ad Hoc / Otro)",
                            "Configuro token/org GitHub y lo busco por API",
                            "Omitir",
                        ],
                        "Omitir",
                    )
                    if como.startswith("Indico"):
                        br = branch or read_env_branch(proyecto)
                        if elegir_repo_guiado(proyecto, dep, br, cat):
                            avance = True
                    elif como.startswith("Configuro"):
                        if configurar_github_interactivo():
                            print("  Rebuscando en tu org...")
                            avance = True
            if args.fix and sugeridos:
                print("\nTrayendo sugeridos de otros repos...")
                avance = True
                for dep, (org, repo, url) in sugeridos.items():
                    br = args.branch or (
                        odoo_to_branch(args.odoo)
                        if args.odoo
                        else read_env_branch(proyecto)
                    )
                    add_modules(proyecto, org, repo, url, br, [dep])
        if not args.fix:
            print("\nCon --fix agrego mismo-repo y sugeridos automáticamente.")
            return
        if not mismo_repo and not total:
            return
        # fix: sparse-checkout add por repo
        if mismo_repo:
            avance = True
        for rp, mods in sorted(mismo_repo.items()):
            dest = proyecto / rp
            print(f"Agregando en {rp}: {' '.join(sorted(mods))}")
            run(git_red(str(dest)) + ["sparse-checkout", "add"] + sorted(mods), cwd=str(dest))
            run(git_red(str(dest)) + ["sparse-checkout", "reapply"], cwd=str(dest))
            repos = load_repos(proyecto)
            for r in repos:
                if r.get("path") == rp:
                    r["modules"] = sorted(set(r.get("modules", [])) | set(mods))
            save_repos(proyecto, repos)
        actualizar_addons_path(proyecto)
        if not avance:
            # Nada nuevo para traer (ni sugeridos, ni mismo-repo, ni guía del
            # usuario): repetir sería buscar lo mismo. Se informa y se sale.
            print("\nSin avances: lo pendiente se resuelve a mano (u omítelo).")
            return
        print("  (reviso cadenas una vez más...)")
    print("⚠ Cadena muy larga, revisa a mano lo que falte.")


def solo_install(proyecto, ver=None, ofrecer_aplicar=True):
    """Instalador standalone sobre proyecto existente. Devuelve True si cambió repos.json."""
    from types import SimpleNamespace

    proyecto = Path(proyecto).resolve()
    if ver is None:
        envf = proyecto / ".env"
        ver = ""
        if envf.exists():
            for line in envf.read_text(encoding="utf-8").splitlines():
                if line.startswith("ODOO_VERSION="):
                    ver = line.split("=", 1)[1].strip()
        if ver not in cargar_versions():
            sys.exit(f"No pude leer ODOO_VERSION válida en {envf}.")
    print(
        f"=== Instalador de módulos ({proyecto.name}, Odoo {ver}, rama {ver}.0 automática) ==="
    )
    repos_antes = (
        (proyecto / "addons" / "repos.json").read_text(encoding="utf-8")
        if (proyecto / "addons" / "repos.json").exists()
        else ""
    )
    puerta_instalacion(proyecto, ver)
    repos_despues = (
        (proyecto / "addons" / "repos.json").read_text(encoding="utf-8")
        if (proyecto / "addons" / "repos.json").exists()
        else ""
    )
    if repos_despues == repos_antes:
        print("\nSin cambios, no hay nada que aplicar.")
        return False
    if actualizar_bundle_desde_estado(proyecto):
        print("  ✓ addons-bundle.json actualizado (todos los módulos).")
    asegurar_queue_job_conf(proyecto)
    if ofrecer_aplicar and es_interactivo():
        if ask_si_no(
            "¿Aplicar ahora? (sync: deps + rebuild + restart)", default_no=False
        ):
            run_sync(
                SimpleNamespace(
                    bundle="",
                    branch="",
                    odoo="",
                    yes=False,
                    no_deploy=False,
                    skip_install=True,
                    proyecto=str(proyecto),
                )
            )
            return True
    if ofrecer_aplicar and es_interactivo() and ask_si_no(
        "¿Reiniciar Odoo ahora? (docker compose restart odoo)", default_no=False
    ):
        subprocess.run(["docker", "compose", "restart", "odoo"], cwd=str(proyecto))
        print("  ✓ Odoo reiniciado. Actualiza la lista de aplicaciones en la UI.")
    elif ofrecer_aplicar:
        print("\nSigue con: omc addons sync  (deps + rebuild)")
    return True


def run_deps_simple(proyecto, enfocar=None):
    """Reporte liviano de depends internos enfocado en módulos nuevos (flujo sync).

    Sin búsqueda en catálogo ni preguntas: solo muestra el estado.
    La resolución con --fix vive en run_deps.
    """
    proyecto = Path(proyecto)
    reporte, mismo_repo, total = analizar_depends(proyecto)
    foco = set(enfocar or [])
    print(seccion("\n== Dependencias entre módulos =="))
    for mod in sorted(reporte):
        if foco and mod not in foco:
            continue
        det = ", ".join(f"{d}[{e}]" for d, e in reporte[mod])
        print(f"  {mod}: {det or '(sin depends)'}")
    if foco and not [m for m in reporte if m in foco]:
        print("  (los nuevos no declaran depends)")
    if mismo_repo:
        print("\nDisponibles en repos ya clonados (mismo repo, sin descargar):")
        for rp, mods in sorted(mismo_repo.items()):
            print(f"  {rp}: {' '.join(sorted(mods))}")
    if total:
        print(f"\nFaltantes (ni en disco ni en base): {' '.join(sorted(total))}")
        print("  (resuélvelos con deps --fix)")
    if not mismo_repo and not total:
        print("✓ Todo resuelto.")


# Parámetros del sistema (ir.config_parameter) que deja la localización AR.
# Se crean si no existen vía scripts/parametros_ar.sh (idempotente).
PARAMETROS_AR = [
    ("report.url", "http://localhost:8069"),
    ("afip.ws.env.type", "homologation"),
]


def _escribir_parametros_ar(salida: Path) -> Path:
    """Genera scripts/parametros_ar.sh (INSERT ... WHERE NOT EXISTS)."""
    lineas = []
    for k, v in PARAMETROS_AR:
        lineas.append(
            f'$PSQL -c "INSERT INTO ir_config_parameter (\\"key\\", \\"value\\") '
            f"SELECT '{k}', '{v}' WHERE NOT EXISTS "
            f"(SELECT 1 FROM ir_config_parameter WHERE \\\"key\\\" = '{k}');\""
        )
    out = Path(salida) / "scripts" / "parametros_ar.sh"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(cargar_template("parametros_ar.sh.tpl"), {
        "PROYECTO": Path(salida).name,
        "PARAMS_SQL": "\n".join(lineas),
    }), encoding="utf-8")
    try:
        out.chmod(0o755)
    except OSError:
        pass
    return out


def _ofrecer_fijar_parametros(salida) -> None:
    """Ofrece correr parametros_ar.sh ahora (necesita BD creada). Si no, indica el comando."""
    manual = "  Parámetros AR cuando la BD exista: ./scripts/parametros_ar.sh <bd>"
    salida = Path(salida).resolve()
    if not es_interactivo():
        print(manual)
        return
    if not ask_si_no("¿Fijar parámetros AR ahora? (necesita BD creada)",
                     default_no=True):
        print(manual)
        return
    r = subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "env",
         f"PGPASSWORD={os.environ.get('POSTGRES_PASSWORD', 'odoo')}",
         "psql", "-U", "odoo", "-d", "postgres", "-tAX",
         "-c", "SELECT datname FROM pg_database WHERE datistemplate=false "
                "AND datname NOT IN ('postgres');"],
        cwd=str(salida), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60)
    bds = [b.strip() for b in (r.stdout or "").splitlines() if b.strip()]
    if r.returncode != 0 or not bds:
        print("  ⚠ No pude listar BDs (¿db apagado o sin BD creada?).")
        print(manual)
        return
    bd = bds[0]
    if len(bds) > 1:
        print("  Bases disponibles:")
        for i, b in enumerate(bds, 1):
            print(f"    {i}) {b}")
        bd = ask_texto(f"¿En cuál fijo? [1-{len(bds)}]", "1")
        bd = bds[int(bd) - 1] if bd.isdigit() and 1 <= int(bd) <= len(bds) else ""
        if not bd:
            print("  Selección inválida.")
            print(manual)
            return
    print(f"  Fijando parámetros AR en '{bd}' ...")
    sc = salida / "scripts" / "parametros_ar.sh"
    rr = subprocess.run(["bash", str(sc), bd], cwd=str(salida))
    if rr.returncode != 0:
        print("  ⚠ Falló. Correlo a mano cuando la BD exista:")
        print(manual)


def bloques_localizacion(salida: Path) -> dict:
    """Bloques Dockerfile desde addons/localizacion.json (apt m2crypto + SECLEVEL + cache).

    Fusiona pip_extra en requirements-odoo.txt (lo crea si falta y hay extras)
    y saca pip_exclude (lo que apt provee, ej M2Crypto). Sin localizacion.json
    (o inválido) devuelve bloques vacíos. Misma fuente para crear y sync.
    """
    import re as _re

    salida = Path(salida)
    vacio = {"APT_PKGS": "", "SECPY_BLOCK": ""}
    locf = salida / "addons" / "localizacion.json"
    if not locf.exists():
        return vacio
    try:
        loc = json.loads(locf.read_text(encoding="utf-8"))
    except ValueError:
        return vacio
    pip_extra = loc.get("pip_extra", []) or []
    pip_exclude = [p.lower() for p in (loc.get("pip_exclude", []) or [])]
    # requirements del repo descargado (dinámico por rama) + extras del perfil
    extras = []
    for l in list(loc.get("repo_requirements", []) or []) + list(pip_extra):
        n = normalizar_req(l.strip())
        if n and n not in extras:
            extras.append(n)
    apt_pkgs = loc.get("apt", []) or []
    seclevel = bool(loc.get("seclevel"))
    pyafipws_cache = bool(loc.get("pyafipws_cache"))
    reqf = salida / "requirements-odoo.txt"
    original = reqf.read_text(encoding="utf-8").splitlines() if reqf.exists() else []

    def base_nom(l):
        m = _re.match(r"^([A-Za-z0-9_.-]+)", l.strip())
        return m.group(1).lower() if m else ""

    cur = [l for l in original if base_nom(l) not in pip_exclude]
    low = {l.lower() for l in cur}
    add = [p for p in extras
           if p.lower() not in low and base_nom(p) not in pip_exclude]
    if add:
        print(f"  + pip de localización: {' '.join(add)}")
    quitados = [l for l in original if base_nom(l) in pip_exclude]
    if quitados:
        print(f"  - pip cubierto por apt: {', '.join(sorted({base_nom(l) for l in quitados}))}")
    if (add or cur != original) and (reqf.exists() or add):
        reqf.write_text("\n".join(cur + add) + "\n", encoding="utf-8")
    apt_pkgs = (" " + " ".join(apt_pkgs)) if apt_pkgs else ""
    secpy = ""
    if seclevel:
        secpy += (
            "# AFIP: openssl SECLEVEL=1 (si no existe el patrón no cambia nada)\n"
            "RUN sed -i 's/SECLEVEL=2/SECLEVEL=1/g' /etc/ssl/openssl.cnf || true\n"
        )
    if pyafipws_cache:
        secpy += (
            "# Cache escribible de pyafipws (ruta según python de la imagen)\n"
            'RUN PYD=$(python3 -c "import pyafipws, os; print(os.path.dirname(pyafipws.__file__))" 2>/dev/null) && '
            '[ -n "$PYD" ] && mkdir -p "$PYD/cache" && chmod 777 "$PYD/cache" || true\n'
        )
    return {"APT_PKGS": apt_pkgs, "SECPY_BLOCK": secpy}


def ensure_dockerfile_sync(proyecto):
    """Asegura Dockerfile + compose en modo build si hay requirements (flujo sync).

    Incluye los extras de localización (addons/localizacion.json: apt m2crypto,
    SECLEVEL, cache pyafipws): si existen, el Dockerfile se (re)genera con ellos
    aunque ya existiera sin esos bloques. Idempotente.
    """
    proyecto = Path(proyecto)
    bloques = bloques_localizacion(proyecto)
    con_loc = bool(bloques["APT_PKGS"] or bloques["SECPY_BLOCK"])
    req = proyecto / "requirements-odoo.txt"
    if not (req.exists() and req.read_text(encoding="utf-8").strip()) and not con_loc:
        return False
    env = leer_env(proyecto)
    ver = env.get("ODOO_VERSION", "")
    try:
        info = cargar_versions().get(ver, {})
    except FileNotFoundError:
        info = {}
    mapping = {
        "PROYECTO": proyecto.name,
        "ODOO_VERSION": ver,
        "ODOO_IMAGE": info.get("odoo", f"odoo:{ver}"),
        "PIP_BREAK": "" if ver == "17" else " --break-system-packages",
        "APT_PKGS": bloques["APT_PKGS"],
        "SECPY_BLOCK": bloques["SECPY_BLOCK"],
    }
    if not (proyecto / "Dockerfile").exists() or con_loc:
        (proyecto / "Dockerfile").write_text(
            render(cargar_template("Dockerfile.tpl"), mapping), encoding="utf-8")
        try:
            (proyecto / ".dockerignore").write_text(
                cargar_template("dockerignore.tpl"), encoding="utf-8")
        except FileNotFoundError:
            pass
        print("  ✓ Dockerfile generado (sync{}).".format(
            " + localización" if con_loc else ""))
    parchear_compose_a_build(proyecto, mapping)
    return True


def asegurar_queue_job_conf(proyecto, args=None) -> bool:
    """Si queue_job está descargado, deja su config en odoo.conf (idempotente).

    Receta del README de OCA/queue: `server_wide_modules` con queue_job y sección
    `[queue_job]` (channels). Respeta valores existentes (fusiona, no pisa) y avisa
    si workers = 0 (el runner no arranca sin workers). Devuelve True si cambió algo.
    """
    from .manifest import iterar_modulos as _iter

    proyecto = Path(proyecto)
    mods = set()
    for r in load_repos(proyecto):
        mods.update(r.get("modules", []) or [])
    for _base in ("addons/custom", "addons/extras"):
        d = proyecto / _base
        if d.is_dir():
            for name, _p in _iter(d):
                mods.add(name)
    if "queue_job" not in mods:
        return False
    conf = proyecto / "config" / "odoo.conf"
    if not conf.exists():
        return False
    txt = conf.read_text(encoding="utf-8")
    import re as _re
    m = _re.search(r"^server_wide_modules\s*=\s*(.+)$", txt, _re.M)
    actual = [x.strip() for x in m.group(1).split(",")] if m else []
    falta_sw = "queue_job" not in actual
    falta_sec = "[queue_job]" not in txt
    if not (falta_sw or falta_sec):
        return False
    workers = (_re.search(r"^workers\s*=\s*(\d+)", txt, _re.M) or [None, "0"])[1]
    if workers == "0":
        print("  ⚠ queue_job necesita workers > 0 (dev tiene 0): el runner no arrancará.")
    debe = "server_wide_modules + [queue_job] channels=root:2"
    if sys.stdin.isatty() and not (args is not None and getattr(args, "yes", False)):
        if not ask_si_no(f"queue_job detectado. ¿Agregar su config a odoo.conf ({debe})?",
                         default_no=False):
            print("  (omitido: el runner no arrancará sin esa config)")
            return False
    else:
        print(f"  queue_job detectado: agregando {debe} ...")
    if falta_sw:
        if m:
            txt = txt.replace(m.group(0),
                              f"server_wide_modules = {','.join(actual + ['queue_job'])}", 1)
        else:
            txt = txt.rstrip("\n") + "\nserver_wide_modules = web,queue_job\n"
    if falta_sec:
        txt = txt.rstrip("\n") + "\n[queue_job]\nchannels = root:2\n"
    conf.write_text(txt, encoding="utf-8")
    print("  ✓ odoo.conf con queue_job (reinicia odoo para que tome efecto).")
    return True


def run_sync(args):
    """Post-despliegue: instala (bundle opcional) + deps + Dockerfile + rebuild.

    Para Odoo ya desplegado al que se le agregan módulos de repos.
    """
    proyecto = find_proyecto(args.proyecto)

    def foto_estado():
        fotos = {}
        for rel in [
            "addons/repos.json",
            "requirements-odoo.txt",
            "Dockerfile",
            "docker-compose.yml",
        ]:
            f = proyecto / rel
            if not f.exists():
                fotos[rel] = None
            elif rel == "addons/repos.json":
                try:
                    fotos[rel] = json.dumps(
                        json.loads(f.read_text(encoding="utf-8")), sort_keys=True
                    )
                except ValueError:
                    fotos[rel] = f.read_text(encoding="utf-8", errors="replace")
            else:
                fotos[rel] = (
                    f.read_text(encoding="utf-8", errors="replace").strip() + "\n"
                )
        return fotos

    antes = foto_estado()
    # 1) Instalador: mismo del inicio (bundle o lista numerada), salvo --bundle/--skip-install
    if args.bundle:
        print(f"== Bundle {args.bundle} ==", flush=True)
        br = args.branch or (odoo_to_branch(args.odoo) if args.odoo else "")
        if not run_bundle_file(proyecto, args.bundle, br, args.odoo):
            sys.exit("Falló el bundle, no sigo.")
    elif not args.skip_install and sys.stdin.isatty() and not args.yes:
        if ask_si_no(
            "¿Descargar módulos nuevos?",
            default_no=True,
        ):
            if not solo_install(proyecto, ofrecer_aplicar=False):
                return  # Nada elegido en puerta_instalacion: vuelta al menú sin ruido
        else:
            return  # no hay nada nuevo: vuelve al menú sin mostrar deps ni aplicar
    # Auto-export: fusiona el estado actual en addons-bundle.json (lo crea si
    # falta) para clonar esta instancia después. Suma sin borrar entradas manuales.
    if actualizar_bundle_desde_estado(proyecto):
        print("  ✓ addons-bundle.json actualizado con el estado actual.")

    # Módulos nuevos de ESTA corrida (para enfocar el reporte en ellos)
    def _mods_de(s):
        try:
            return {
                f"{r.get('path')}/{m}"
                for r in json.loads(s or "[]")
                for m in r.get("modules", [])
            }
        except ValueError:
            return set()

    _ahora_repos = (
        (proyecto / "addons" / "repos.json").read_text(encoding="utf-8")
        if (proyecto / "addons" / "repos.json").exists()
        else ""
    )
    nuevos = sorted(_mods_de(_ahora_repos) - _mods_de(antes.get("addons/repos.json")))
    nuevos_nombres = sorted({x.rsplit("/", 1)[-1] for x in nuevos})
    print(seccion("\n== Dependencias =="), flush=True)
    from types import SimpleNamespace

    run_check_deps(SimpleNamespace(proyecto=str(proyecto), json_out=False))
    run_deps_simple(proyecto, enfocar=nuevos_nombres)
    req = proyecto / "requirements-odoo.txt"
    # --- MENÚ ÚNICO: aplicar todo (conf ya mapeada al descargar) ---
    if args.no_deploy:
        print(
            f"\nPara aplicar: cd {proyecto} && docker compose up -d --build && docker compose restart odoo"
        )
        return
    det_nuevos = ", ".join(sorted(nuevos))
    # Config de módulos especiales antes de aplicar (ej queue_job -> odoo.conf)
    asegurar_queue_job_conf(proyecto, args)
    if args.yes or not sys.stdin.isatty():
        aplicar = True
    else:
        aplicar = ask_si_no(
            f"Aplicar cambios ({det_nuevos})?",
            default_no=False,
        )
    if not aplicar:
        print(f"\nPara aplicar luego: cd {proyecto} && docker compose up -d --build")
        return
    # 1) traer faltantes (mismo-repo/catálogo) con re-verificación en cadena
    from types import SimpleNamespace

    run_deps(
        SimpleNamespace(
            proyecto=str(proyecto),
            fix=True,
            porcelain=False,
            enfocar="",
            branch=args.branch,
            odoo=args.odoo,
        )
    )
    # 2) re-escanear externas con lo nuevo
    print(seccion("\n== Re-verificando dependencias externas con lo nuevo =="), flush=True)
    run_check_deps(SimpleNamespace(proyecto=str(proyecto), json_out=False))
    # 3) Dockerfile solo si hay requirements
    if req.exists() and req.read_text().strip():
        ensure_dockerfile_sync(proyecto)
        print("  ✓ Dockerfile + compose en modo build.")
    else:
        print("Sin requirements-odoo.txt: no hace falta Dockerfile.")
    # 4) rebuild si cambió Dockerfile/compose/requirements; si no, restart
    if foto_estado() != antes:
        print("\nHubo cambios: rebuild (verás el progreso)")
        r = subprocess.run(
            ["docker", "compose", "up", "-d", "--build"], cwd=str(proyecto)
        )
        if r.returncode == 0:
            print(
                "✓ Aplicado. Actualiza la lista de aplicaciones en la UI. Logs: docker compose logs -f odoo"
            )
        else:
            print("⚠ Falló. Revisa: docker compose logs -f")
    else:
        print("\nSin cambios de build: restart para que Odoo escanee.")
        r = subprocess.run(["docker", "compose", "restart", "odoo"], cwd=str(proyecto))
        if r.returncode == 0:
            print("✓ Odoo reiniciado. Actualiza la lista de aplicaciones en la UI.")
        else:
            print("⚠ Falló el restart. Revisa: docker compose ps")
    # 5) resumen: registrados pero ausentes en disco (omitidos o desaparecidos de la rama)
    try:
        from .manifest import load_repos
        faltantes = []
        for _r in load_repos(proyecto):
            _base = proyecto / (_r.get("path") or "")
            if not _r.get("path"):
                continue
            if _r.get("single"):
                if not _base.is_dir():
                    faltantes.append(f"{_r.get('repo')}/(repo)")
                continue
            for _m in _r.get("modules", []):
                if _m and not (_base / _m).is_dir():
                    faltantes.append(f"{_r.get('repo')}/{_m}")
        if faltantes:
            print(f"\n⚠ Módulos registrados pero no descargados ({len(faltantes)}): "
                  f"{' '.join(sorted(set(faltantes)))}")
            print("  Revisá rama del repo o nombre (pudo desaparecer de la rama).")
        else:
            print("\n✓ Todos los módulos registrados están en disco.")
        # drift: repos cuyo remoto avanzó desde lo fijado (omc addons pull actualiza)
        try:
            movidos = []
            for _r in load_repos(proyecto):
                _url, _br, _sha = _r.get("url", ""), _r.get("branch", ""), _r.get("sha", "")
                if not (_url and _br and _sha):
                    continue
                _rem = remote_head(_url, _br)
                if _rem and _rem != _sha:
                    movidos.append(f"{_r.get('repo')}@{_br} ({_sha[:7]}→{_rem[:7]})")
            if movidos:
                print(f"\n⚠ Repos con cambios upstream ({len(movidos)}): "
                      f"{' '.join(sorted(set(movidos)))}")
                print("  Mismo bundle, distinto código: `omc addons pull` para actualizar.")
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass


def run_export_bundle(args):
    proyecto = find_proyecto(args.proyecto)
    salida = Path(args.salida)
    if not salida.is_absolute():
        salida = proyecto / args.salida
    if salida.exists() and not args.force:
        sys.exit(f"Ya existe {salida}. Usa --force para sobrescribir u otro --salida.")
    data = bundle_desde_estado(proyecto)
    if not data["modulos"]:
        print("Sin repos en addons/repos.json: nada que exportar.")
        return
    salida.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"✓ Bundle exportado: {salida} ({len(data['modulos'])} repos)")
    print(
        "  Para levantar instancia similar: omc addons bundle "
        f"{salida.name} --odoo {leer_env(proyecto).get('ODOO_VERSION', 'X')}"
    )


def run_add(args):
    proyecto = find_proyecto(args.proyecto)
    branch = args.branch or (
        odoo_to_branch(args.odoo) if args.odoo else read_env_branch(proyecto)
    )
    if not branch:
        sys.exit("Indica --branch 18.0 o --odoo 18")
    cat = load_catalog()
    org, repo, url = resolve_repo(args.org, args.repo, args.url, cat)
    add_modules(proyecto, org, repo, url, branch, args.modulos)
    asegurar_queue_job_conf(proyecto, args)
    print(
        "\nReinicia Odoo para verlos: docker compose restart odoo && docker compose logs -f odoo"
    )


def run_bundle_file(proyecto, archivo: str, branch: str = "", odoo: str = "") -> bool:
    """Bundle por ruta (usado por sync/crear). Devuelve False si falla."""
    from types import SimpleNamespace

    proyecto = Path(proyecto)
    bp = Path(archivo)
    if not bp.is_absolute():
        bp = proyecto / archivo
    if not bp.exists():
        alt = data_path(Path(archivo).name)
        if alt and alt.exists():
            bp = alt
    if not bp.exists():
        print(f"  ⚠ No existe la plantilla bundle: {archivo}")
        return False
    try:
        run_bundle(
            SimpleNamespace(
                proyecto=str(proyecto), archivo=str(bp), branch=branch, odoo=odoo
            )
        )
        return True
    except SystemExit as e:
        print(f"  ⚠ {e}")
        return False


def run_bundle(args):
    """Descarga TODOS los repos/módulos de una plantilla bundle de una sola vez."""
    proyecto = find_proyecto(args.proyecto)
    default_branch = args.branch or (
        odoo_to_branch(args.odoo) if args.odoo else read_env_branch(proyecto)
    )
    bundle_path = Path(args.archivo)
    if not bundle_path.is_absolute():
        bundle_path = proyecto / args.archivo
    if not bundle_path.exists():
        # buscar junto al helper / master como fallback
        alt = Path(__file__).parent / Path(args.archivo).name
        if alt.exists():
            bundle_path = alt
    if not bundle_path.exists():
        sys.exit(f"No existe la plantilla bundle: {args.archivo}")
    data = json.loads(bundle_path.read_text(encoding="utf-8"))
    entradas = data.get("modulos", data if isinstance(data, list) else [])
    if isinstance(entradas, dict):
        entradas = [{"org": k, **v} for k, v in entradas.items()]
    cat = load_catalog()
    total_ok, total_fail = [], []
    for e in entradas:
        if not isinstance(e, dict) or e.get("repo", "").startswith("_"):
            continue
        if not e.get("repo") or not e.get("modules"):
            continue
        branch = e.get("branch") or default_branch
        if not branch:
            sys.exit(
                "El bundle no trae branch y no hay --odoo/--branch ni ODOO_VERSION en .env"
            )
        org, repo, url = resolve_repo(
            e.get("org", "oca"), e["repo"], e.get("url", ""), cat
        )
        print(f"\n== {org}/{repo}@{branch}: {', '.join(e['modules'])} ==")
        ok, fail = add_modules(proyecto, org, repo, url, branch, e["modules"])
        total_ok += [f"{repo}/{m}" for m in ok]
        total_fail += [f"{repo}/{m}" for m in fail]
    print(f"\nBundle listo: {len(total_ok)} ok, {len(total_fail)} omitidos.")
    if total_fail:
        print(f"  Omitidos: {' '.join(total_fail)}")
    asegurar_queue_job_conf(proyecto, args)
    print(
        "\nReinicia Odoo para verlos: docker compose restart odoo && docker compose logs -f odoo"
    )


def run_pull(args):
    proyecto = find_proyecto(args.proyecto)
    repos = load_repos(proyecto)
    if args.repo:
        repos = [r for r in repos if r["repo"] == args.repo]
    if not repos:
        print("Nada para actualizar (repos.json vacío).")
        return
    for r in repos:
        p = proyecto / r["path"]
        if not p.is_dir():
            print(f"  ⚠ {r['path']}: no existe, omitido.")
            continue
        print(f"Pull {r['path']} ({r['branch']}) ...")
        git_pull(str(p))
        from .manifest import anotar_sha
        anotar_sha(r, p)
    from .manifest import save_repos
    save_repos(proyecto, repos)
    print("Listo. Reinicia: docker compose restart odoo")


def run_status(args):
    proyecto = find_proyecto(args.proyecto)
    repos = load_repos(proyecto)
    if not repos:
        print("Sin repos (addons/repos.json vacío).")
        return
    conf = proyecto / "config" / "odoo.conf"
    txt = conf.read_text(encoding="utf-8") if conf.exists() else ""
    for r in repos:
        print(f"\n{r['path']}  {r['url']}@{r['branch']}")
        in_conf = r["path"].replace("addons/", "/mnt/extra-addons/") in txt
        print(f"  {'✓' if in_conf else '✗ NO'} en addons_path de odoo.conf")
        for m in r.get("modules", []):
            ok = "✓" if (proyecto / r["path"] / m).is_dir() else "✗ falta en disco"
            print(f"  {ok} {m}")


def run_quitar(args):
    """Saca módulos (sparse-checkout set sin ellos). Si no queda ninguno, borra el clon."""
    proyecto = find_proyecto(args.proyecto)
    repos = load_repos(proyecto)
    # buscar entradas que contengan cada módulo
    pendientes = {m: None for m in args.modulos}
    for r in repos:
        for m in args.modulos:
            if m in r.get("modules", []) and pendientes[m] is None:
                pendientes[m] = r
    for m, r in pendientes.items():
        if r is None:
            print(f"  ⚠ {m}: no está registrado en repos.json.")
            continue
        dest = proyecto / r["path"]
        resto = sorted(set(r["modules"]) - {m})
        if resto and dest.is_dir():
            run(git_red(str(dest)) + ["-C", str(dest), "sparse-checkout", "set"] + resto)
            run(git_red(str(dest)) + ["-C", str(dest), "sparse-checkout", "reapply"])
            r["modules"] = resto
            print(f"  ✓ {m} fuera de {r['path']} (quedan: {' '.join(resto)})")
        else:
            import shutil as _sh

            _sh.rmtree(dest, ignore_errors=True)
            repos[:] = [x for x in repos if x.get("path") != r["path"]]
            print(f"  ✓ {m} fuera y clon {r['path']} eliminado (no quedaba nada).")
    save_repos(proyecto, repos)
    actualizar_addons_path(proyecto)
    print("Reinicia Odoo: docker compose restart odoo")


def run_fix_paths(args):
    """Migra a sin-symlinks: borra accesos directos legacy y regenera addons_path."""
    proyecto = find_proyecto(args.proyecto)
    n = limpiar_symlinks(proyecto)
    print(f"Symlinks legacy borrados: {n}")
    actualizar_addons_path(proyecto)
    print("Reinicia Odoo: docker compose restart odoo")


def run_list_catalog(args):
    cat = load_catalog()
    orgs = (
        ["oca", "adhoc", "cybrosys", "mates", "codize"]
        if args.org == "all"
        else [args.org]
    )
    if args.org == "all" and cat.get("custom"):
        orgs.append("custom")
    for org in orgs:
        print(f"\n== {org.upper()} ==")
        for e in cat.get(org, []):
            if isinstance(e, dict):
                print(f"  {e.get('repo', ''):30} {e.get('desc', '')}")
    print(
        "\nOtro repo cualquiera: add ... --url <https|ssh> [--branch X] (privados: export GITHUB_TOKEN=...)"
    )
    print(
        "Agregar enlaces al catálogo: catalog-add --org adhoc --repo X --url https://... [--desc ...]"
    )


def elegir_proyecto() -> Path:
    """Menú de proyectos existentes (dirs con docker-compose.yml)."""
    cands: list[Path] = []
    try:
        if (Path.cwd() / "docker-compose.yml").exists():
            cands.append(Path.cwd().resolve())
    except OSError:
        pass
    try:
        for d in sorted(projects_home().iterdir()):
            if d.is_dir() and (d / "docker-compose.yml").exists() and d.resolve() not in cands:
                cands.append(d.resolve())
    except OSError:
        pass
    if not cands:
        return Path(ask_texto("Ruta del proyecto", ".") or ".").resolve()
    labels = []
    for c in cands:
        tag = ""
        try:
            for line in (c / ".env").read_text(encoding="utf-8").splitlines():
                if line.startswith("ENTORNO="):
                    tag = f" [{line.split('=', 1)[1].strip()}]"
                    break
            if not tag and (c / "scripts" / "backup.sh").exists():
                tag = " [produccion?]"
        except OSError:
            pass
        labels.append(f"{c}{tag}")
    elegida = ask_opcion("¿En qué proyecto?", labels, labels[0])
    return cands[labels.index(elegida)]


def _detectar_ide_bin(preferencia: str = "auto") -> str | None:
    """Prefiere codium si existe, si no code. preferencia: auto|codium|vscode"""
    if preferencia == "codium":
        return "codium" if shutil.which("codium") else None
    if preferencia == "vscode":
        return "code" if shutil.which("code") else None
    # auto: codium primero (usuario usa VSCodium), luego code
    if shutil.which("codium"):
        return "codium"
    if shutil.which("code"):
        return "code"
    if shutil.which("code-oss"):
        return "code-oss"
    return None


def _load_jsonc(path: Path) -> dict | None:
    """Lee JSON con // comentarios (VS Code jsonc)."""
    try:
        txt = path.read_text(encoding="utf-8")
        # quita líneas // y comentarios inline simples
        lines = []
        for ln in txt.splitlines():
            if ln.strip().startswith("//"):
                continue
            # quita // inline solo si aparecen fuera de strings (aprox)
            if "//" in ln and '"' not in ln.split("//", 1)[0]:
                ln = ln.split("//", 1)[0]
            lines.append(ln)
        clean = "\n".join(lines)
        # quita comas colgantes
        clean = re.sub(r",\s*([}\]])", r"\1", clean)
        return json.loads(clean)
    except Exception:  # noqa: BLE001
        return None


def generar_vscode(salida: Path, mapping: dict, ide: str = "auto", instalar: bool = False, force: bool = False) -> list:
    """Genera .vscode/{settings,extensions,launch,tasks}.json + opencode.json con merge no destructivo.

    En prod (ENTORNO=produccion, VPS) solo genera opencode.json en modo terminal con --force; .vscode nunca en prod.
    """
    salida = Path(salida)
    es_prod = False
    try:
        es_prod = leer_env(salida).get("ENTORNO") == "produccion"
    except Exception:  # noqa: BLE001
        es_prod = mapping.get("ENTORNO") == "produccion"
    if es_prod and not force:
        print("  ⚠ prod (VPS): opencode/.vscode solo en dev; use --force para generar solo opencode.json en modo terminal (sin IDE/extensión)")
        return []
    # en prod con --force solo opencode.json, sin .vscode
    solo_opencode = es_prod and force
    vs = salida / ".vscode"
    if not solo_opencode:
        vs.mkdir(parents=True, exist_ok=True)
    creados = []
    # opencode.json en raíz (siempre en dev, solo con --force en prod)
    try:
        oc_texto = render(cargar_template("opencode.json.tpl"), mapping)
        if sin_renderizar(oc_texto):
            print(f"  ⚠ opencode.json.tpl quedó con placeholders: {sin_renderizar(oc_texto)}")
        oc_dest = salida / "opencode.json"
        if not oc_dest.exists():
            oc_dest.write_text(oc_texto, encoding="utf-8")
            creados.append("opencode.json")
        else:
            existente = _load_jsonc(oc_dest)
            try:
                nuevo = json.loads(re.sub(r",\s*([}\]])", r"\1", "\n".join(
                    l for l in oc_texto.splitlines() if not l.strip().startswith("//")
                )))
            except Exception:  # noqa: BLE001
                nuevo = None
            if existente is not None and nuevo is not None:
                merged = merge_json(existente, nuevo)
                if merged != existente:
                    bkp = oc_dest.with_suffix(".json.bak")
                    if not bkp.exists():
                        shutil.copy2(oc_dest, bkp)
                    oc_dest.write_text(json.dumps(merged, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
                    creados.append("opencode.json (merge)")
                else:
                    creados.append("opencode.json (ya existe)")
            else:
                creados.append("opencode.json (existe, no tocado)")
    except FileNotFoundError:
        pass
    if solo_opencode:
        # prod --force: solo opencode.json, informar
        print("  → prod --force: generado solo opencode.json (modo terminal, sin .vscode ni extensiones)")
        return creados
    pares = [
        ("vscode-settings.json.tpl", "settings.json"),
        ("vscode-extensions.json.tpl", "extensions.json"),
        ("vscode-launch.json.tpl", "launch.json"),
        ("vscode-tasks.json.tpl", "tasks.json"),
    ]
    for tpl, out in pares:
        texto = render(cargar_template(tpl), mapping)
        if sin_renderizar(texto):
            print(f"  ⚠ {tpl} quedó con placeholders sin sustituir: {sin_renderizar(texto)}")
        dest = vs / out
        if dest.exists():
            existente = _load_jsonc(dest)
            try:
                nuevo = json.loads(re.sub(r",\s*([}\]])", r"\1", "\n".join(
                    l for l in texto.splitlines() if not l.strip().startswith("//")
                )))
            except Exception:  # noqa: BLE001
                nuevo = None
            if existente is not None and nuevo is not None:
                merged = merge_json(existente, nuevo)
                # backup si cambia
                if merged != existente:
                    bkp = dest.with_suffix(dest.suffix + ".bak")
                    if not bkp.exists():
                        shutil.copy2(dest, bkp)
                    dest.write_text(json.dumps(merged, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
                    creados.append(f".vscode/{out} (merge)")
                else:
                    creados.append(f".vscode/{out} (ya existe, sin cambios)")
            else:
                creados.append(f".vscode/{out} (existe, no tocado)")
            continue
        dest.write_text(texto, encoding="utf-8")
        creados.append(f".vscode/{out}")
    # instalar extensiones si se pide y hay bin
    if instalar:
        bin_ide = _detectar_ide_bin(ide)
        if not bin_ide:
            print("  ⚠ No se encontró `codium` ni `code` para instalar extensiones (solo se generó .vscode/).")
        else:
            exts = ( _load_jsonc(vs / "extensions.json") or {}).get("recommendations", [])
            if not exts:
                try:
                    txt = (vs / "extensions.json").read_text(encoding="utf-8")
                    exts = json.loads(re.sub(r",\s*([}\]])", r"\1", "\n".join(
                        l for l in txt.splitlines() if not l.strip().startswith("//")
                    ))).get("recommendations", [])
                except Exception:  # noqa: BLE001
                    exts = []
            for e in exts:
                print(f"  Instalando {e} en {bin_ide} ...")
                subprocess.run([bin_ide, "--install-extension", e, "--force"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return creados


def run_dev(args=None):
    """Menú 13 / `omc dev|ide`: Desarrollo (IDE + navegador)."""
    proj = None
    if args is not None and getattr(args, "proyecto", None):
        proj = Path(args.proyecto).resolve()
    else:
        # si hay flag --proyecto usarlo, si no elegir
        try:
            from .core import find_proyecto
            # si args trae proyecto explícito ya resuelto arriba
            if args is not None and getattr(args, "proyecto", None):
                proj = find_proyecto(args.proyecto)
            else:
                # intentar cwd, si no elegir
                try:
                    proj = find_proyecto()
                except SystemExit:
                    from .flows import elegir_proyecto as _elegir  # noqa: PLC0415
                    proj = _elegir()
        except Exception:  # noqa: BLE001
            proj = Path.cwd()
    # si es instalación directa sin submenú (ej --ide codium --instalar)
    ide_flag = getattr(args, "ide", None) if args is not None else None
    instalar_flag = getattr(args, "instalar", False) if args is not None else False
    solo_generar = getattr(args, "solo_generar", False) if args is not None else False
    if ide_flag:
        env = leer_env(proj)
        es_prod = env.get("ENTORNO") == "produccion"
        force = bool(getattr(args, "force", False))
        if es_prod and not force:
            print("  ⚠ prod (VPS): opencode/.vscode solo en dev; use --force para generar solo opencode.json en modo terminal (sin IDE/extensión)")
            return
        mapping = {"PROYECTO": proj.name, "ODOO_VERSION": env.get("ODOO_VERSION", "18"), "ENTORNO": env.get("ENTORNO", "desarrollo")}
        ide_norm = "codium" if ide_flag == "codium" else "vscode" if ide_flag == "vscode" else "auto"
        generar_vscode(proj, mapping, ide=ide_norm, instalar=instalar_flag and not solo_generar, force=force)
        if es_prod and force:
            print(f"\n✓ opencode.json generado en {proj}/opencode.json (prod --force, modo terminal sin .vscode)")
        else:
            print(f"\n✓ .vscode generado en {proj}/.vscode  (ide={ide_norm})")
        print("  Chrome: My Odoo Webkit https://chromewebstore.google.com/detail/my-odoo-webkit/fdohfkgekkoehlofibieijojjcmlbdok?hl=es")
        return
    # submenú interactivo
    while True:
        print(marco("Desarrollo — IDE + navegador", [
            "1) Configurar VS Code / Codium (.vscode)",
            "2) Verificar extensiones IDE",
            "3) Extensiones Chrome (my-odoo-webkit)",
            "4) Regenerar AGENTS.md del proyecto",
            tenue("0) Volver"),
        ], pie="↑/↓ + Enter · número + Enter · ESC sale"))
        # usar elegir_interactivo si hay tty
        try:
            from .tui import elegir_interactivo as _eleg  # noqa: PLC0415
            sel = _eleg(["1) Configurar VS Code / Codium (.vscode)",
                         "2) Verificar extensiones IDE",
                         "3) Extensiones Chrome (my-odoo-webkit)",
                         "4) Regenerar AGENTS.md del proyecto",
                         "0) Volver"], titulo_txt="Desarrollo — ¿qué hacer?")
            if sel is not None:
                if sel == 4:
                    return
                choice = str(sel + 1) if sel < 4 else "0"
            else:
                choice = ask_opcion(["Configurar VS Code / Codium", "Verificar extensiones", "Extensiones Chrome", "Regenerar AGENTS.md", "Volver"], "Elegí")
                choice = {"Configurar VS Code / Codium": "1", "Verificar extensiones": "2",
                          "Extensiones Chrome": "3", "Regenerar AGENTS.md": "4", "Volver": "0"}.get(choice, "0")
        except Exception:  # noqa: BLE001
            choice = ask_texto("Elige [0-4]", "0")
        if choice == "0":
            return
        env = leer_env(proj)
        mapping = {"PROYECTO": proj.name, "ODOO_VERSION": env.get("ODOO_VERSION", "18"),
                   "MAILPIT_PORT": env.get("MAILPIT_PORT", "8025")}
        if choice == "1":
            if env.get("ENTORNO") == "produccion":
                print("  ⚠ prod (VPS): .vscode/IDE solo en dev local. ¿Generar solo opencode.json en modo terminal?")
                if not (es_interactivo() and ask_si_no("¿Generar opencode.json con --force?", False)):
                    print("  Cancelado (prod sin --force no genera .vscode)")
                    continue
                creados = generar_vscode(proj, {**mapping, "ENTORNO": "produccion"}, ide="auto", instalar=False, force=True)
                print("\nvscode creados/merge (prod --force terminal):")
                for c in creados:
                    print(f"  - {c}")
                continue
            pref = "auto"
            if es_interactivo():
                pref_raw = ask_opcion(["Auto (codium > code)", "VSCodium (codium)", "VS Code (code)", "Solo generar (sin instalar)"], "IDE")
                pref = {"Auto (codium > code)": "auto", "VSCodium (codium)": "codium",
                        "VS Code (code)": "vscode", "Solo generar (sin instalar)": "auto"}.get(pref_raw, "auto")
                instalar = pref_raw != "Solo generar (sin instalar)"
            else:
                instalar = False
            creados = generar_vscode(proj, mapping, ide=pref, instalar=instalar)
            print("\nvscode creados/merge:")
            for c in creados:
                print(f"  - {c}")
            bin_ide = _detectar_ide_bin(pref)
            if bin_ide:
                print(f"  Abrir: {bin_ide} {proj}")
            else:
                print(f"  Abrir: codium {proj}  o  code {proj}")
        elif choice == "2":
            bin_ide = _detectar_ide_bin("auto")
            if not bin_ide:
                print("  No se encontró `codium` ni `code`. Instalá VSCodium/VS Code y reintentá.")
                continue
            try:
                r = subprocess.run([bin_ide, "--list-extensions"], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
                instaladas = set((r.stdout or "").lower().splitlines())
            except Exception:  # noqa: BLE001
                instaladas = set()
            exts = ["ms-python.python", "ms-python.vscode-pylance", "charliermarsh.ruff",
                    "ms-vscode.vscode-json", "ms-azuretools.vscode-docker", "trinhanhngoc.vscode-odoo"]
            print(f"  IDE detectado: {bin_ide}")
            for e in exts:
                print(f"    {'✓' if e.lower() in instaladas else '✗'} {e}")
            if es_interactivo() and ask_si_no("¿Instalar faltantes?", False):
                for e in exts:
                    if e.lower() not in instaladas:
                        print(f"  Instalando {e} ...")
                        subprocess.run([bin_ide, "--install-extension", e, "--force"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif choice == "3":
            print(marco("Chrome — My Odoo Webkit (principal)", [
                "My Odoo Webkit v1.3.0 — 76 usuarios",
                "https://chromewebstore.google.com/detail/my-odoo-webkit/fdohfkgekkoehlofibieijojjcmlbdok?hl=es",
                "• Model inspector (modelo/ID/vista/action/XMLID/context/domain)",
                "• Record viewer (JSON-RPC, search, copy JSON)",
                "• Field explorer (type/label/relation, searchable)",
                "• ORM snippets (browse/search/create/write/unlink)",
                "• Shell commands (odoo-bin, odoo.sh, psql, lnav)",
                "Alternativas: Odoo Toolbox, Odoo Debug (?debug=1, Ctrl+.)",
            ]))
            if es_interactivo() and shutil.which("xdg-open") and ask_si_no("¿Abrir Chrome Web Store?", False):
                subprocess.Popen(["xdg-open", "https://chromewebstore.google.com/detail/my-odoo-webkit/fdohfkgekkoehlofibieijojjcmlbdok?hl=es"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif choice == "4":
            dest = proj / "AGENTS.md"
            bkp = dest.with_suffix(".md.bak") if dest.exists() else None
            if bkp and not bkp.exists() and dest.exists():
                shutil.copy2(dest, bkp)
            dest.write_text(render(cargar_template("agents-proyecto.md.tpl"), mapping), encoding="utf-8")
            print(f"  ✓ AGENTS.md regenerado en {dest}" + (f" (backup {bkp})" if bkp else ""))


def menu_principal() -> str:
    """Menú inicial. Devuelve acción o 'crear' para seguir flujo clásico."""
    acciones = [
        ("crear", "Crear proyecto nuevo (docker-compose Odoo)"),
        ("sync", "Módulos: descargar y aplicar (bundle/lista)"),
        ("localizacion", "Localización AR: dependencias + Dockerfile"),
        ("web", "Web: nginx + certbot [prod]"),
        ("rclone", "Rclone / Drive [prod]"),
        ("monitor", "Monitor web (contenedores + logs)"),
        ("github", "GitHub: token + org/usuario"),
        ("backup", "Backup manual [prod]"),
        ("restore", "Restaurar BD [prod]"),
        ("migrar", "Migrar proyecto a nueva versión Odoo (OCA)"),
        ("proxy", "Proxy multinstancia (nginx compartido) [prod/infra]"),
        ("migrar_vps", "Migrar instancia a otro VPS (paquete completo)"),
        ("dev", "Desarrollo (IDE + navegador)"),
        ("salir", "Salir"),
    ]
    print(banner_omc(PKG_VERSION))
    labels = [v for _k, v in acciones if _k != "salir"]
    # Opciones navegables: 1..13 + 0 Salir (14 items, 0 navegable)
    nav_items = [f"{i}) {lab}" for i, lab in enumerate(labels, 1)] + ["0) Salir"]
    pie_menu = ("↑/↓ + Enter · número + Enter · 0 sale | "
                "Habitual: 1 crear → 2 módulos → 3 AR → 8 backup")
    # Intento con flechas si hay tty real
    try:
        from .tui import elegir_interactivo
        sel = elegir_interactivo(nav_items, titulo_txt="¿Qué quiere hacer?",
                                 pie=pie_menu)
        if sel is not None:
            if sel == len(nav_items) - 1:
                return "salir"
            return acciones[sel][0]
    except Exception:  # noqa: BLE001
        pass
    # Fallback clásico numérico (agrupado por fase, sin renumerar)
    filas = [tenue("  — Crear —")]
    for i, lab in enumerate(labels, 1):
        if i == 4:
            filas.append(tenue("  — Publicar [prod] —"))
        if i == 6:
            filas.append(tenue("  — Operar —"))
        filas.append(f"  {numero(f'{i})')} {texto_menu(lab)}")
    filas.append(tenue("  0) Salir"))
    print(marco(
        "¿Qué quiere hacer?",
        filas,
        pie=pie_menu,
    ))
    r = ask_texto(f"Elige [0-{len(labels)}]", "1")
    if r == "0":
        return "salir"
    if r.isdigit() and 1 <= int(r) <= len(labels):
        return acciones[int(r) - 1][0]
    return next((k for k, v in acciones if v == r), "crear")


def run_proxy_init(salida=None) -> Path:
    """Crea/actualiza el proxy central (/opt/proxy): compose + red + up. Idempotente.

    No pide nada: seguro en menú y en no-interactivo. Devuelve la ruta.
    """
    from .compose import PROXY_NETWORK, PROXY_PROJECT, generar_proxy_compose

    root = Path(salida).resolve() if salida else (projects_home() / PROXY_PROJECT).resolve()
    asegurar_escribible(root, "proxy")
    for d in ("conf.d", "letsencrypt", "certbot-www"):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "docker-compose.yml").write_text(generar_proxy_compose(), encoding="utf-8")
    (root / "conf.d" / "gzip.conf").write_text(
        render(cargar_template("nginx-gzip.conf.tpl"), {"PROYECTO": PROXY_PROJECT}),
        encoding="utf-8")
    (root / ".gitignore").write_text(cargar_template("gitignore.tpl"), encoding="utf-8")
    envf = root / ".env"
    if not envf.exists():
        envf.write_text(f"PROYECTO={PROXY_PROJECT}\nENTORNO=infraestructura\n",
                        encoding="utf-8")
    print(f"\nProxy central en: {root}")
    r = subprocess.run(["docker", "network", "inspect", PROXY_NETWORK],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if r.returncode != 0:
        print(f"  Creando red {PROXY_NETWORK} ...")
        r = subprocess.run(["docker", "network", "create", PROXY_NETWORK])
        if r.returncode != 0:
            sys.exit(f"No pude crear la red {PROXY_NETWORK} (¿docker accesible?).")
    else:
        print(f"  Red {PROXY_NETWORK} ya existe.")
    r = subprocess.run(["docker", "compose", "up", "-d"], cwd=str(root))
    if r.returncode != 0:
        sys.exit(f"No pude levantar el proxy en {root} (revisá docker).")
    print("  ✓ nginx escuchando 80/443 (conf.d/ vacío hasta conectar sitios).")
    print("  Siguiente: omc web --proxy --proyecto <ruta> --dominio <dom> --email <mail>")
    return root


def run_proxy(args=None):
    """Menú 11 / `omc proxy`: inicializa el proxy central (idempotente)."""
    salida = getattr(args, "salida", None) if args is not None else None
    run_proxy_init(salida)


def run_list(args):
    """Lista instancias detectadas."""
    from .core import projects_home, leer_env
    base = projects_home()
    projs = []
    try:
        for d in sorted(base.iterdir()):
            if d.is_dir() and (d / "docker-compose.yml").exists():
                env = leer_env(d)
                projs.append((d.name, env.get("ODOO_VERSION", "?"), env.get("ODOO_PORT", "?"),
                              env.get("ENTORNO", "?"), env.get("DOMINIO", "")))
    except OSError:
        pass
    if getattr(args, "json", False):
        import json as _json
        print(_json.dumps([
            {"nombre": n, "odoo": v, "puerto": p, "entorno": e, "dominio": dom}
            for n, v, p, e, dom in projs
        ]))
        return
    if not projs:
        print(f"No hay proyectos en {base}")
        return
    print(titulo(f"Proyectos en {base}:"))
    for n, v, p, e, dom in projs:
        print(f"  {n:20} Odoo {v:5} puerto {p:5} {e:12} {dom}")


def run_doctor(args):
    """Valida compose/conf/addons por instancia."""
    from .core import projects_home, leer_env, sin_renderizar
    import subprocess
    targets = []
    if args.proyecto:
        targets = [Path(args.proyecto).resolve()]
    else:
        base = projects_home()
        try:
            targets = [d for d in sorted(base.iterdir()) if d.is_dir() and (d / "docker-compose.yml").exists()]
        except OSError:
            targets = []
    ok_all = True
    report = []
    machine = bool(getattr(args, "json", False))
    for proj in targets:
        if not machine:
            print(titulo(f"\n== {proj.name} =="))
        errs = []
        if not (proj / "docker-compose.yml").exists():
            errs.append("falta docker-compose.yml")
        else:
            # validar compose (solo sintaxis sin render) — si no hay docker, se omite
            try:
                r = subprocess.run(["docker", "compose", "config"], cwd=str(proj),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=20)
                if r.returncode != 0:
                    errs.append(f"compose config falla: {(r.stderr or '')[:200]}")
            except FileNotFoundError:
                if not machine:
                    print("  · docker no disponible: no se validó compose")
        if not (proj / "config" / "odoo.conf").exists():
            errs.append("falta config/odoo.conf")
        else:
            txt = (proj / "config" / "odoo.conf").read_text(encoding="utf-8", errors="replace")
            if "{{" in txt:
                errs.append(f"odoo.conf con placeholders sin resolver: {sin_renderizar(txt)}")
        env = leer_env(proj)
        for k in ("ODOO_VERSION", "ODOO_IMAGE", "POSTGRES_IMAGE"):
            if not env.get(k):
                errs.append(f".env sin {k}")
        # addons
        repos = proj / "addons" / "repos.json"
        if repos.exists():
            try:
                data = __import__("json").loads(repos.read_text(encoding="utf-8"))
                for r in data:
                    if not (proj / r.get("path", "")).exists():
                        errs.append(f"repo no existe en disco: {r.get('path')}")
            except ValueError:
                errs.append("repos.json inválido")
        if args.fix and errs:
            # fix mínimo: regenerar addons_path
            try:
                from .addonsops import actualizar_addons_path
                actualizar_addons_path(proj)
                if not machine:
                    print("  fix: addons_path actualizado")
            except Exception as _e:  # noqa: BLE001
                if not machine:
                    print(f"  fix falló: {_e}")
        if errs:
            ok_all = False
            if not machine:
                for e in errs:
                    print(err(f"  ✗ {e}"))
        elif not machine:
            print(ok("  ✓ OK"))
        report.append({"proyecto": proj.name, "ok": not errs, "errores": errs})
    if machine:
        import json as _json
        print(_json.dumps(report))
        if not ok_all:
            sys.exit(2)
        return
    if not ok_all:
        print("\nDoctor: hay errores (ver arriba).")
        if not args.fix:
            print("Prueba con --fix para reparar addons_path.")
        sys.exit(2)
    else:
        print("\nDoctor: todo OK.")


def _resolver_proyecto(args) -> Path:
    """Proyecto desde --proyecto o cwd (exige docker-compose.yml)."""
    if getattr(args, "proyecto", None):
        p = Path(args.proyecto).resolve()
        if not (p / "docker-compose.yml").exists():
            sys.exit(f"{p} no parece un proyecto (sin docker-compose.yml).")
        return p
    p = find_proyecto()
    if not (p / "docker-compose.yml").exists():
        sys.exit(f"{p} no parece un proyecto (sin docker-compose.yml).")
    return p


def run_web(args):
    """Configura nginx+certbot [prod]. Pide --dominio/--email o interactivo."""
    import types

    proj = _resolver_proyecto(args)
    if not exigir_prod(proj, "Web nginx/certbot"):
        return
    modo_configurar_web(types.SimpleNamespace(
        proyecto=str(proj),
        dominio=getattr(args, "dominio", None),
        email=getattr(args, "email", None),
        staging=bool(getattr(args, "staging", False)),
        proxy=bool(getattr(args, "proxy", False)),
        standalone=bool(getattr(args, "standalone", False)),
        no_input=bool(getattr(args, "no_input", False)),
    ))


def run_rclone(args):
    """Configura rclone/Drive [prod]."""
    import types

    proj = _resolver_proyecto(args)
    if not exigir_prod(proj, "Rclone/Drive"):
        return
    modo_configurar_rclone(types.SimpleNamespace(
        proyecto=str(proj),
        rclone_remote=getattr(args, "rclone_remote", None),
        no_input=bool(getattr(args, "no_input", False)),
    ))


def _monitor_cmd() -> list:
    """Comando para lanzar el monitor: binario instalado o módulo del paquete."""
    exe = shutil.which("omc-monitor")
    if exe:
        return [exe]
    return [sys.executable, "-m", "omc.webapp"]


def _monitor_service_info():
    """Lee el unit systemd del monitor: token/puerto/host reales + estado.

    Devuelve dict o None si no hay unit. Nunca falla (sin systemd: activo=False).
    La URL y el token del monitor SOLO se muestran en la opción 6.
    """
    import re
    unit = Path.home() / ".config" / "systemd" / "user" / "omc-monitor.service"
    try:
        txt = unit.read_text(encoding="utf-8")
    except OSError:
        return None

    def _env(key, default=""):
        m = re.search(rf"^Environment={key}=(.*)$", txt, re.M)
        return m.group(1).strip() if m else default

    m = re.search(r"ExecStart=.*--port\s+(\d+)", txt)
    port = int(m.group(1)) if m else 8765
    m = re.search(r"ExecStart=.*--host\s+(\S+)", txt)
    host = m.group(1) if m else "127.0.0.1"
    activo = False
    try:
        r = subprocess.run(["systemctl", "--user", "is-active", "--quiet", "omc-monitor"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        activo = r.returncode == 0
    except Exception:  # noqa: BLE001
        pass
    return {"existe": True, "activo": activo, "host": host, "port": port,
            "token": _env("ODOO_WEB_TOKEN")}


def run_monitor(args):
    """Monitor web solo-lectura (contenedores + logs + métricas)."""
    _ = args
    base_cmd = _monitor_cmd()
    info = _monitor_service_info()
    if info and info["token"]:
        estado = "activo" if info["activo"] else "instalado (detenido)"
        print(f"\nMonitor del servicio: {estado}")
        print(f"  URL:   http://{info['host']}:{info['port']}")
        print(f"  Token: {info['token']}")
    modo = ask_opcion(
        "Monitor web (solo lectura: contenedores + logs + métricas)",
        ["Ver en esta terminal (Ctrl+C lo detiene)", "Fondo (libera la terminal)",
         "Detener el de fondo", "Volver"],
        "Ver en esta terminal (Ctrl+C lo detiene)",
    )
    if modo == "Detener el de fondo":
        subprocess.run([*base_cmd, "--stop"])
        return
    if modo == "Volver":
        return
    fondo = modo == "Fondo (libera la terminal)"
    sugerido = info["port"] if info else 8765
    while True:
        port = ask_puerto("Puerto del monitor", sugerido)
        if puerto_en_uso(port):
            sugerido = puerto_libre(port + 1)
            print(f"  ⚠ El puerto {port} está ocupado. Libre sugerido: {sugerido}")
            continue
        break
    donde = preguntar("¿Dónde lo ve?", "vps" if info and info["host"] != "127.0.0.1" else "local",
                      ["local", "vps"])
    host = "127.0.0.1" if donde == "local" else "0.0.0.0"
    token_sugerido = info["token"] if info and info["token"] else secrets.token_urlsafe(16)
    token = preguntar("Token (vacío = sugerido)", token_sugerido)
    if donde == "local":
        print(f"\nAbra http://localhost:{port}  (token: {token})")
    else:
        print(f"\nAbra http://TU_IP:{port}  (token: {token})")
    cmd = [*base_cmd, "--port", str(port), "--host", host, "--token", token]
    if fondo:
        subprocess.run([*cmd, "--fondo"])
        return
    print("Ctrl+C para detener el monitor.\n")
    subprocess.run(cmd)


def run_github(args):
    """Configura token + org de GitHub (~/.config, 0600)."""
    _ = args
    configurar_github_interactivo()


def run_backup(args):
    """Backup manual vía scripts/backup.sh [prod]."""
    proj = _resolver_proyecto(args)
    if not exigir_prod(proj, "Backup"):
        return
    script = proj / "scripts" / "backup.sh"
    if not script.exists():
        print(f"  ⚠ {script} no existe (proyecto sin backups configurados).")
        return
    bd = ""
    if es_interactivo():
        bd = ask_texto("Base a respaldar (vacío = elegir de lista)", "").strip()
    subprocess.run(["./scripts/backup.sh"] + ([bd] if bd else []), cwd=str(proj))


def run_restore(args):
    """Restaura BD vía scripts/restore.sh [prod]."""
    proj = _resolver_proyecto(args)
    if not exigir_prod(proj, "Restore"):
        return
    script = proj / "scripts" / "restore.sh"
    if not script.exists():
        print(f"  ⚠ {script} no existe (proyecto sin backups configurados).")
        return
    flags = []
    if getattr(args, "neutralizar", False):
        flags.append("--neutralizar")
    if getattr(args, "sin_neutralizar", False):
        flags.append("--sin-neutralizar")
    subprocess.run(["./scripts/restore.sh"] + flags, cwd=str(proj))


def _elegir_bd(proj: Path, db_arg, que: str) -> str:
    """BD desde --db o pick interactivo (lista de postgres). Sin tty exige --db."""
    if db_arg:
        return str(db_arg).strip()
    bds = []
    try:
        r = subprocess.run(
            ["docker", "compose", "exec", "-T", "db", "psql", "-U", "odoo",
             "-d", "postgres", "-tAX", "-c",
             "SELECT datname FROM pg_database WHERE datistemplate=false "
             "AND datname NOT IN ('postgres');"],
            cwd=str(proj), text=True, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=30)
        if r.returncode == 0:
            bds = [b.strip() for b in (r.stdout or "").splitlines() if b.strip()]
    except Exception:  # noqa: BLE001
        pass
    if not bds:
        sys.exit(f"No pude listar BDs de {proj.name} (¿db arriba?). Pasá --db <nombre>.")
    if len(bds) == 1:
        print(f"  BD: {bds[0]} (única).")
        return bds[0]
    if not es_interactivo():
        sys.exit(f"Indicá la BD con --db (hay: {' '.join(bds)}).")
    el = ask_opcion(f"¿BD para {que}?", bds, bds[0])
    return el


def run_logs(args):
    """Logs del proyecto (follow). Corto para el ciclo típico."""
    proj = _resolver_proyecto(args)
    servicio = getattr(args, "servicio", None) or "odoo"
    tail = getattr(args, "tail", None) or 200
    print(f"Logs de {servicio} (Ctrl+C para salir).")
    subprocess.run(["docker", "compose", "logs", "-f", f"--tail={tail}", servicio],
                   cwd=str(proj))


def run_update(args):
    """Actualiza un módulo (-u) en contenedor efímero. Pide --db si falta."""
    proj = _resolver_proyecto(args)
    mod = getattr(args, "modulo", None)
    if not mod:
        sys.exit("Indicá el módulo: omc update <modulo> [--db <bd>].")
    bd = _elegir_bd(proj, getattr(args, "db", None), f"actualizar {mod}")
    print(f"Actualizando {mod} en {bd} ...")
    r = subprocess.run(["docker", "compose", "run", "--rm", "odoo",
                        "odoo", "-d", bd, "-u", mod, "--stop-after-init"],
                       cwd=str(proj))
    if r.returncode != 0:
        sys.exit(f"Falló el update de {mod} (revisá el log de arriba).")
    print(f"✓ {mod} actualizado. Reiniciá: docker compose restart odoo")


def run_test(args):
    """Corre tests de un módulo (--test-enable) en contenedor efímero."""
    proj = _resolver_proyecto(args)
    mod = getattr(args, "modulo", None)
    if not mod:
        sys.exit("Indicá el módulo: omc test <modulo> [--db <bd>].")
    bd = _elegir_bd(proj, getattr(args, "db", None), f"testear {mod}")
    print(f"Testeando {mod} en {bd} ...")
    r = subprocess.run(["docker", "compose", "run", "--rm", "odoo",
                        "odoo", "-d", bd, "-u", mod,
                        "--test-enable", "--stop-after-init"],
                       cwd=str(proj))
    if r.returncode != 0:
        sys.exit(f"Fallaron los tests de {mod} (revisá el log de arriba).")
    print(f"✓ Tests de {mod} OK.")


def run_migrar_vps(args):
    """Migrar instancia a otro VPS: para odoo, backup completo y empaqueta.

    Genera un tar.gz transportable con addons-bundle.json + full_backup(s)
    + .env + repos.json + MANIFEST.json. No toca volúmenes nombrados.
    """
    import tarfile
    import time

    todo = bool(getattr(args, "todo", False))
    consistente = bool(getattr(args, "consistente", False))
    # Resolver alcance
    if todo:
        base = projects_home()
        try:
            targets = [d for d in sorted(base.iterdir())
                       if d.is_dir() and (d / "docker-compose.yml").exists()]
        except OSError:
            targets = []
        # excluir proxy (infra)
        targets = [p for p in targets if p.name != "proxy"]
        if not targets:
            print(f"No hay proyectos en {base}")
            return
    else:
        # un proyecto: menú o --proyecto
        try:
            proj = _resolver_proyecto(args) if getattr(args, "proyecto", None) else elegir_proyecto()
        except SystemExit as e:
            print(e.code)
            return
        targets = [proj]
    # Validar prod
    validos = []
    for p in targets:
        if not exigir_prod(p, f"Migrar {p.name}"):
            continue
        if not (p / "scripts" / "backup.sh").exists():
            print(f"  ⚠ {p.name}: sin scripts/backup.sh (¿proyecto viejo?). Omitido.")
            continue
        validos.append(p)
    if not validos:
        print("Nada para migrar.")
        return
    # Parar escrituras y hacer backups
    artefactos = []
    for proj in validos:
        print(f"\n== {proj.name} ==")
        # parar odoo para consistencia filestore
        print("  Parando odoo para backup consistente ...")
        subprocess.run(["docker", "compose", "stop", "odoo"], cwd=str(proj))
        if consistente:
            subprocess.run(["docker", "compose", "stop", "db"], cwd=str(proj))
            subprocess.run(["docker", "compose", "up", "-d", "db"], cwd=str(proj))
            # esperar pg_isready como restore
            for _ in range(30):
                r = subprocess.run(["docker", "compose", "exec", "-T", "db",
                                    "pg_isready", "-U", "odoo", "-d", "postgres"],
                                   cwd=str(proj), stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
                if r.returncode == 0:
                    break
                time.sleep(2)
        # listar BDs
        bds = []
        try:
            r = subprocess.run(["docker", "compose", "exec", "-T", "db",
                                "psql", "-U", "odoo", "-d", "postgres",
                                "-tAX", "-c",
                                "SELECT datname FROM pg_database WHERE datistemplate=false AND datname NOT IN ('postgres');"],
                               cwd=str(proj), text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, timeout=30)
            if r.returncode == 0:
                bds = [b.strip() for b in (r.stdout or "").splitlines() if b.strip()]
        except Exception:  # noqa: BLE001
            pass
        if not bds:
            print("  ⚠ No pude listar BDs, omitido.")
            subprocess.run(["docker", "compose", "start", "odoo"], cwd=str(proj))
            continue
        # asegurar bundle actualizado
        try:
            from .addonsops import actualizar_bundle_desde_estado
            actualizar_bundle_desde_estado(proj)
        except Exception:  # noqa: BLE001
            pass
        for bd in bds:
            print(f"  Backup {bd} ...")
            r = subprocess.run(["./scripts/backup.sh", bd], cwd=str(proj))
            if r.returncode != 0:
                print(f"  ⚠ backup de {bd} falló, omitido.")
                continue
            # buscar último full_backup generado
            import glob as _glob
            cands = sorted(_glob.glob(str(proj / "backups" / f"full_backup_{bd}_*.tar.gz")))
            if cands:
                artefactos.append((proj, Path(cands[-1])))
        # levantar
        subprocess.run(["docker", "compose", "start", "odoo"], cwd=str(proj))
        if consistente:
            subprocess.run(["docker", "compose", "up", "-d"], cwd=str(proj))
    if not artefactos:
        print("Sin backups generados, nada que empaquetar.")
        return
    # Empaquetado host
    ts = time.strftime("%Y%m%d_%H%M%S")
    host = __import__("socket").gethostname().split(".")[0]
    out = projects_home() / f"migrar_{host}_{ts}.tar.gz"
    # Manifest
    manifest = {"host": host, "fecha": ts, "proyectos": []}
    import hashlib as _hash
    for proj, f in artefactos:
        try:
            sha = _hash.sha256(f.read_bytes()).hexdigest()[:12]
        except Exception:  # noqa: BLE001
            sha = ""
        manifest["proyectos"].append({"proyecto": proj.name, "archivo": f.name, "sha": sha})
    # Crear tar
    import json as _json
    import io as _io
    with tarfile.open(out, "w:gz") as tf:
        for proj, f in artefactos:
            tf.add(str(f), arcname=f"{proj.name}/{f.name}")
            # adjuntar bundle y env del proyecto
            for rel in ["addons-bundle.json", ".env", "addons/repos.json", "config/odoo.conf"]:
                src = proj / rel
                if src.exists():
                    tf.add(str(src), arcname=f"{proj.name}/{rel}")
        # MANIFEST.json
        data = _json.dumps(manifest, indent=2).encode()
        ti = tarfile.TarInfo("MANIFEST.json")
        ti.size = len(data)
        ti.mtime = int(time.time())
        tf.addfile(ti, _io.BytesIO(data))
    print(f"\n✓ Paquete migrar en {out}")
    print(f"  Proyectos: {', '.join(p.name for p in validos)}")
    print("  Restaurar en destino: descomprimir y por cada proyecto ./scripts/restore.sh <bd> <tgz>")
    # No borrar artefactos locales (ya están en backups/)


def run_list_modules(args):
    branch = args.branch or (odoo_to_branch(args.odoo) if args.odoo else "")
    if not branch:
        # fallback a .env del proyecto si se está dentro
        try:
            proyecto = find_proyecto(args.proyecto)
            branch = read_env_branch(proyecto)
        except SystemExit:
            pass
    if not branch:
        sys.exit("Indica --branch 18.0 o --odoo 18")
    cat = load_catalog()
    org, repo, url = resolve_repo(args.org, args.repo, args.url, cat)
    print(f"Listando {org}/{repo} rama {branch} ...")
    try:
        dirs, unico, _ramas = list_remote_topdirs(url, branch)
    except SystemExit:
        print(f"(No se pudo listar {org}/{repo}@{branch}.)")
        return
    if dirs is None:
        print(f"(No se pudo listar {org}/{repo}@{branch}.)")
        return
    if unico:
        print(f"\n{org}/{repo}@{branch} ES el módulo (repo de un solo módulo).")
        print(
            f"  Descárgalo con: omc addons add --repo {repo} --org {org}"
            + (
                f" --url {url}"
                if org.lower() not in ("oca", "adhoc", "cybrosys", "mates", "codize")
                else ""
            )
            + f" --branch {branch}"
        )
        return
    print(f"\nMódulos probables en {org}/{repo}@{branch} ({len(dirs)}):")
    for i, d in enumerate(sorted(dirs), 1):
        print(f"  {i:3}) {d}")
    print("  (elige por número o nombre: '1,5' o 'auditlog,sentry')")


def run_catalog_add(args):
    """Agrega un enlace al catálogo (queda para elegirlo por número después).

    Basta organización + repositorio si el org es conocido
    (oca->OCA, adhoc->ingadhoc, cybrosys->CybroOdoo, mates->odoomates).
    """
    cat_path = data_path("addons-catalog.json") or data_path_write("addons-catalog.json")
    data = json.loads(cat_path.read_text(encoding="utf-8")) if cat_path.exists() else {}
    org = args.org.lower()
    url = args.url.strip()
    if not url:
        base = KNOWN_ORGS.get(org)
        if not base:
            sys.exit(f"Para org '{org}' (desconocido) pasa --url explícito.")
        url = f"https://github.com/{base}/{args.repo}"
    if org not in data or not isinstance(data.get(org), list):
        data[org] = []
    if any(isinstance(e, dict) and e.get("repo") == args.repo for e in data[org]):
        print(f"'{args.repo}' ya está en [{org}].")
        return
    data[org].append({"repo": args.repo, "url": url, "desc": args.desc or ""})
    cat_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"✓ Agregado a [{org}] en {cat_path}: {args.repo} -> {url}")
def crear_proyecto(args):
    """Crea un proyecto completo (flujo clásico de main)."""
    versions = cargar_versions()
    nombre = args.nombre or preguntar("Nombre del proyecto", "mi-odoo")
    entorno = args.entorno or preguntar("¿Entorno?", "desarrollo", ENTORNOS)
    version = args.version or preguntar("¿Versión Odoo?", "18", sorted(versions.keys()))
    puerto_default = str(args.puerto or 8069)
    if args.puerto:
        puerto = args.puerto
        if puerto_en_uso(puerto):
            libre = puerto_libre(puerto + 1)
            print(f"  ⚠ Puerto {puerto} en uso, se usa {libre} en su lugar.")
            puerto = libre
    else:
        while True:
            puerto = ask_puerto("Puerto HTTP Odoo", int(puerto_default))
            if puerto_en_uso(puerto):
                print(
                    f"  ⚠ El puerto {puerto} ya está en uso. Libre sugerido: {puerto_libre(puerto + 1)}"
                )
                puerto_default = str(puerto_libre(puerto + 1))
                if not es_interactivo():
                    puerto = int(puerto_default)
                    break
                continue
            break
    # Puerto gevent/dev 8072 en host: configurable para no chocar entre proyectos (solo desarrollo)
    if entorno == "desarrollo":
        if args.gevent_port:
            gevent_port = args.gevent_port
            if puerto_en_uso(gevent_port):
                libre = puerto_libre(gevent_port + 1)
                print(
                    f"  ⚠ Puerto gevent {gevent_port} en uso, se usa {libre} en su lugar."
                )
                gevent_port = libre
        elif args.no_input or not es_interactivo():
            gevent_port = puerto_libre(8072)
        else:
            while True:
                sugerido_gp = str(puerto_libre(8072))
                gevent_port = ask_puerto(
                    "Puerto longpolling/dev (host → 8072)", int(sugerido_gp)
                )
                if puerto_en_uso(gevent_port):
                    print(
                        f"  ⚠ El puerto {gevent_port} ya está en uso. Libre sugerido: {puerto_libre(gevent_port + 1)}"
                    )
                    continue
                break
        print(f"  HTTP    : host {puerto} → contenedor 8069")
        print(f"  Gevent  : host {gevent_port} → contenedor 8072")
    else:
        gevent_port = 8072  # no se expone en prod, solo referencia
    # Mailpit solo en dev (buzón local: ningún mail real sale del VPS)
    mailpit_port = puerto_libre(8025) if entorno == "desarrollo" else 8025
    if entorno == "desarrollo":
        print(f"  Mailpit : host {mailpit_port} → buzón dev (SMTP interno 1025)")
    if args.password:
        print("Aviso: --password por argv es visible en `ps`; preferí ODOO_DB_PASSWORD en env.", file=sys.stderr)
        pg_password = args.password
    elif os.environ.get("ODOO_DB_PASSWORD"):
        pg_password = os.environ["ODOO_DB_PASSWORD"]
    elif entorno == "produccion":
        sugerido = secrets.token_urlsafe(16)
        if args.no_input or not es_interactivo():
            pg_password = sugerido
            print(f"Password Postgres generado: {pg_password}")
        else:
            r = preguntar("Password Postgres (vacío = generar aleatorio)", sugerido)
            pg_password = r or sugerido
    else:
        pg_password = preguntar("Password Postgres", "odoo")
    if args.admin_password:
        print("Aviso: --admin-password por argv es visible en `ps`; preferí ODOO_ADMIN_PASSWORD en env.", file=sys.stderr)
        admin_passwd = args.admin_password
    elif os.environ.get("ODOO_ADMIN_PASSWORD"):
        admin_passwd = os.environ["ODOO_ADMIN_PASSWORD"]
    elif args.no_input or not es_interactivo():
        admin_passwd = "admin" if entorno == "desarrollo" else secrets.token_urlsafe(12)
    else:
        admin_passwd = preguntar(
            "Master password Odoo (admin_passwd)",
            "admin" if entorno == "desarrollo" else secrets.token_urlsafe(12),
        )
    info = versions[version]
    dev = entorno == "desarrollo"
    # --- Recursos: dev fijos; prod pregunta el VPS y reparte (flags pisan) ---
    odoo_cpus, odoo_mem, db_cpus, db_mem = "1.0", "2G", "0.5", "1G"
    odoo_cpus_res, odoo_mem_res, db_cpus_res, db_mem_res = "0.5", "1G", "0.25", "512M"
    pg = {
        "PG_SHARED_BUFFERS": "128MB",
        "PG_EFFECTIVE_CACHE": "512MB",
        "PG_WORK_MEM": "8MB",
        "PG_MAINT_MEM": "64MB",
        "PG_MAX_CONN": "50",
    }
    odoo_workers = "0"
    limites = {}
    # --- Web pública (solo prod): nginx + certbot opcional ---
    nginx, dominio, email, staging = "no", "", "", False
    rclone_remote = args.rclone_remote or "gdrive"
    if not dev:
        if args.dominio:
            dominio, nginx = args.dominio, ("no" if args.sin_nginx else "si")
        elif not args.no_input and es_interactivo() and not args.sin_nginx:
            if (
                preguntar(
                    "¿Exponer con nginx + HTTPS (Let's Encrypt)?", "no", ["si", "no"]
                )
                == "si"
            ):
                nginx = "si"
                dominio = preguntar("Dominio (ej odoo.midominio.com)", "")
                email = args.email or preguntar("Email para Let's Encrypt", "")
                if (
                    preguntar("¿Certificado de PRUEBA (staging)?", "no", ["si", "no"])
                    == "si"
                ):
                    staging = True
            else:
                print("  Prod sin nginx: Odoo directo en ODOO_PORT.")
        email = args.email or email
        staging = staging or args.staging
        if nginx == "si" and not dominio:
            # Sin dominio no hay Let's Encrypt ni nginx con sentido: prod directo
            print(
                "  ⚠ Sin dominio no hay certbot: prod directo en ODOO_PORT (sin nginx)."
            )
            nginx = "no"
        if nginx == "si" and dominio:
            print(f"  Web     : https://{dominio} (nginx) + staging={staging}")
    # --- VPS (solo prod): pregunta vCPU/RAM y reparte límites + tuning + workers ---
    vcpus_info, ram_info = "", ""
    if not dev:
        import os as _os

        try:
            nloc = str(_os.cpu_count() or 4)
        except Exception:  # noqa: BLE001
            nloc = "4"
        try:
            with open("/proc/meminfo") as _f:
                KB = int([l for l in _f if l.startswith("MemTotal")][0].split()[1])
            gloc = str(max(int(round(KB / 1024 / 1024)), 1))
        except Exception:  # noqa: BLE001
            gloc = "4"
        if args.vcpus:
            vcpus = float(args.vcpus)
        elif not args.no_input and es_interactivo():
            vcpus = ask_float(
                f"vCPUs del VPS (esta máquina tiene {nloc}, solo sugerencia)",
                float(nloc),
            )
        else:
            vcpus = float(nloc)
        if args.ram_gb:
            ram_gb = float(args.ram_gb)
        elif not args.no_input and es_interactivo():
            ram_gb = ask_float(
                f"RAM GB del VPS (acá hay {gloc}, solo sugerencia)", float(gloc)
            )
        else:
            ram_gb = 4.0
        rep = reparto_vps(vcpus, ram_gb, nginx == "si")
        odoo_cpus, odoo_mem = (
            args.odoo_cpus or rep["ODOO_CPUS"],
            args.odoo_mem or rep["ODOO_MEM"],
        )
        odoo_cpus_res, odoo_mem_res = rep["ODOO_CPUS_RES"], rep["ODOO_MEM_RES"]
        db_cpus, db_mem = args.db_cpus or rep["DB_CPUS"], args.db_mem or rep["DB_MEM"]
        db_cpus_res, db_mem_res = rep["DB_CPUS_RES"], rep["DB_MEM_RES"]
        pg = {
            k: rep[k]
            for k in (
                "PG_SHARED_BUFFERS",
                "PG_EFFECTIVE_CACHE",
                "PG_WORK_MEM",
                "PG_MAINT_MEM",
                "PG_MAX_CONN",
            )
        }
        odoo_workers = rep["ODOO_WORKERS"]
        limites = {"ODOO_LIMIT_SOFT": rep["ODOO_LIMIT_SOFT"],
                   "ODOO_LIMIT_HARD": rep["ODOO_LIMIT_HARD"]}
        vcpus_info, ram_info = str(vcpus), str(ram_gb)
        print(
            f"  VPS     : {vcpus} vCPU / {ram_gb}GB -> odoo {odoo_cpus}/{odoo_mem} "
            f"db {db_cpus}/{db_mem} workers {odoo_workers}"
        )
    # Sin symlinks: Odoo ve los repos vía addons_path múltiple (el helper agrega cada repo)
    base_addons_path = (
        "/mnt/extra-addons/custom,/mnt/extra-addons/extras,/mnt/extra-addons"
    )
    mapping = {
        "PROYECTO": nombre,
        "ENTORNO": entorno,
        "ODOO_VERSION": version,
        "ODOO_IMAGE": info["odoo"],
        "POSTGRES_IMAGE": info["postgres"],
        "ODOO_PORT": str(puerto),
        "ODOO_GEVENT_PORT": str(gevent_port),
        "MAILPIT_PORT": str(mailpit_port),
        "ADDONS_PATH": base_addons_path,
        "ADMIN_PASSWD": admin_passwd,
        "PG_PASSWORD": pg_password,
        # pip viejo en Odoo 17 (Debian 11): sin --break-system-packages
        "PIP_BREAK": "" if version == "17" else " --break-system-packages",
        "NGINX": nginx,
        "DOMINIO": dominio,
        "ODOO_HOST": "odoo",
        "CERTBOT_EMAIL": email,
        "CERTBOT_STAGING": " --staging" if staging else "",
        "RCLONE_REMOTE": rclone_remote,
        "ODOO_BUILD_OR_IMAGE": f"image: {info['odoo']}",
        "ODOO_WORKERS": odoo_workers,
        **limites,
        "VPS_VCPUS": vcpus_info,
        "VPS_RAM_GB": ram_info,
        "DB_DEPLOY": bloque_deploy(db_cpus, db_mem, db_cpus_res, db_mem_res),
        "ODOO_DEPLOY": bloque_deploy(odoo_cpus, odoo_mem, odoo_cpus_res, odoo_mem_res),
        **pg,
    }
    if not dev:
        if nginx == "si" and dominio:
            mapping["ODOO_PORTS"] = '    expose:\n      - "8069"\n'
            nginx_tpl = cargar_template("compose-nginx-block.yml.tpl")
            mapping["NGINX_SERVICES"] = render(nginx_tpl, mapping)
        else:
            mapping["ODOO_PORTS"] = f'    ports:\n      - "{puerto}:8069"\n'
            mapping["NGINX_SERVICES"] = ""
        mapping["RCLONE_SERVICE"] = render(
            cargar_template("compose-rclone-block.yml.tpl"), mapping
        )
    else:
        mapping["ODOO_PORTS"] = ""
        mapping["NGINX_SERVICES"] = ""
        mapping["RCLONE_SERVICE"] = ""  # rclone/backup/restore son de prod
    salida = default_salida(nombre, args.salida)
    if not args.salida and not args.no_input and es_interactivo():
        salida = Path(preguntar("Carpeta del proyecto", str(salida)) or str(salida)).resolve()
    asegurar_escribible(salida, "proyectos")
    print(f"\nGenerando en: {salida}")
    print(f"  Entorno : {entorno}")
    print(f"  Odoo    : {info['odoo']}")
    print(f"  Postgres: {info['postgres']}")
    (salida / "addons").mkdir(parents=True, exist_ok=True)
    (salida / "config").mkdir(parents=True, exist_ok=True)
    (salida / "addons" / "custom").mkdir(parents=True, exist_ok=True)
    (salida / "addons" / "oca").mkdir(parents=True, exist_ok=True)
    (salida / "addons" / "adhoc").mkdir(parents=True, exist_ok=True)
    (salida / "addons" / "cybrosys").mkdir(parents=True, exist_ok=True)
    (salida / "addons" / "mates").mkdir(parents=True, exist_ok=True)
    (salida / "addons" / "codize").mkdir(parents=True, exist_ok=True)
    (salida / "addons" / "extras").mkdir(parents=True, exist_ok=True)
    (salida / "addons" / "custom" / ".gitkeep").touch(exist_ok=True)
    (salida / "addons" / "oca" / ".gitkeep").touch(exist_ok=True)
    (salida / "addons" / "adhoc" / ".gitkeep").touch(exist_ok=True)
    (salida / "addons" / "cybrosys" / ".gitkeep").touch(exist_ok=True)
    (salida / "addons" / "mates" / ".gitkeep").touch(exist_ok=True)
    (salida / "addons" / "codize" / ".gitkeep").touch(exist_ok=True)
    (salida / "addons" / "extras" / ".gitkeep").touch(exist_ok=True)
    (salida / "addons" / "extras" / "LEEME.txt").write_text(
        "Módulos sueltos (zips de Odoo Apps): descomprime cada uno en subcarpeta propia.\n",
        encoding="utf-8",
    )
    if not (salida / "addons" / "repos.json").exists():
        (salida / "addons" / "repos.json").write_text("[]\n", encoding="utf-8")
        # Stub que delega en el paquete + versión de referencia + ejemplo de bundle
    (salida / "odoo-addons.py").write_text(stub_addons(), encoding="utf-8")
    (salida / ".omc-version").write_text(PKG_VERSION + "\n", encoding="utf-8")
    try:
        ej = data_text("addons-bundle.ejemplo.json")
        if not (salida / "addons-bundle.ejemplo.json").exists():
            (salida / "addons-bundle.ejemplo.json").write_text(ej, encoding="utf-8")
    except FileNotFoundError:
        pass

    compose = generar_compose(entorno, mapping)
    conf = generar_odoo_conf(entorno, mapping)
    readme = render(cargar_template("README.md.tpl"), mapping)
    gitignore = cargar_template("gitignore.tpl")
    (salida / "docker-compose.yml").write_text(compose, encoding="utf-8")
    (salida / "config" / "odoo.conf").write_text(conf, encoding="utf-8")
    env_lines = [
        f"# {nombre} | {entorno} | odoo {version}",
        f"ENTORNO={entorno}",
        f"ODOO_VERSION={version}",
        f"ODOO_IMAGE={info['odoo']}",
        f"POSTGRES_IMAGE={info['postgres']}",
        f"POSTGRES_PASSWORD={pg_password}",
        f"ODOO_PORT={puerto}",
        f"ODOO_GEVENT_PORT={gevent_port}",
        f"MAILPIT_PORT={mailpit_port}",
        f"PG_SHARED_BUFFERS={pg['PG_SHARED_BUFFERS']}",
        f"PG_EFFECTIVE_CACHE={pg['PG_EFFECTIVE_CACHE']}",
        f"PG_WORK_MEM={pg['PG_WORK_MEM']}",
        f"PG_MAINT_MEM={pg['PG_MAINT_MEM']}",
        f"PG_MAX_CONN={pg['PG_MAX_CONN']}",
        f"ODOO_CPUS={odoo_cpus}",
        f"ODOO_MEM={odoo_mem}",
        f"DB_CPUS={db_cpus}",
        f"DB_MEM={db_mem}",
    ]
    creados_extra = []
    if not dev:
        env_lines += [
            f"DOMINIO={dominio}",
            f"CERTBOT_EMAIL={email}",
            f"RCLONE_REMOTE={rclone_remote}",
        ]
        if vcpus_info:
            env_lines += [f"VPS_VCPUS={vcpus_info}", f"VPS_RAM_GB={ram_info}"]
        # nginx/ + scripts/ + backups/
        (salida / "nginx").mkdir(exist_ok=True)
        (salida / "scripts").mkdir(exist_ok=True)
        (salida / "backups").mkdir(exist_ok=True)
        (salida / "backups" / ".gitkeep").touch(exist_ok=True)
        if nginx == "si" and dominio:
            (salida / "nginx" / "nginx.conf").write_text(
                render(cargar_template("nginx.conf.tpl"), mapping), encoding="utf-8"
            )
            (salida / "letsencrypt").mkdir(exist_ok=True)
            (salida / "certbot-www").mkdir(exist_ok=True)
            creados_extra += ["nginx/nginx.conf", "letsencrypt/", "certbot-www/"]
        for tpl, out in [
            ("backup.sh.tpl", "scripts/backup.sh"),
            ("restore.sh.tpl", "scripts/restore.sh"),
            ("rclone.conf.tpl", "scripts/rclone.conf.ejemplo"),
        ]:
            (salida / out).write_text(
                render(cargar_template(tpl), mapping), encoding="utf-8"
            )
            creados_extra.append(out)
        (salida / "scripts" / "backup.sh").chmod(0o755)
        (salida / "scripts" / "restore.sh").chmod(0o755)
        # rclone.conf real vacío: evita que docker cree un directorio al montar el servicio rclone
        if not (salida / "scripts" / "rclone.conf").exists():
            (salida / "scripts" / "rclone.conf").write_text(
                "# Configúralo con: omc rclone --proyecto .\n",
                encoding="utf-8",
            )
            creados_extra.append("scripts/rclone.conf (vacío: configurar)")
    else:
        # dev: sin stack web/backup (son de prod)
        pass
    (salida / ".env").write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    (salida / ".env.ejemplo").write_text(
        render(cargar_template("env.ejemplo.tpl"),
               dict(mapping, POSTGRES_PASSWORD="cambiar-esta-clave")),
        encoding="utf-8")
    (salida / "README.md").write_text(readme, encoding="utf-8")
    (salida / ".gitignore").write_text(gitignore, encoding="utf-8")
    (salida / "AGENTS.md").write_text(
        render(cargar_template("agents-proyecto.md.tpl"), mapping), encoding="utf-8")
    # --- IDE (.vscode) opcional: --ide codium|vscode|auto|none (solo dev; prod solo con --force para opencode.json) ---
    ide_opt = getattr(args, "ide", "none")
    force_opt = bool(getattr(args, "force", False))
    if ide_opt and ide_opt != "none":
        ide_norm = "codium" if ide_opt == "codium" else "vscode" if ide_opt == "vscode" else "auto"
        creados_vs = generar_vscode(salida, mapping, ide=ide_norm, instalar=False, force=force_opt)
        if creados_vs:
            print("\nIDE .vscode:")
            for c in creados_vs:
                print(f"  - {c}")
            print("  Chrome: My Odoo Webkit https://chromewebstore.google.com/detail/my-odoo-webkit/fdohfkgekkoehlofibieijojjcmlbdok?hl=es")
    elif es_interactivo() and not args.no_input and not args.sin_addons and entorno == "desarrollo":
        # pregunta opt-in solo en menú interactivo dev (prod nunca)
        if ask_si_no("¿Configurar VS Code / Codium (.vscode)?", False):
            pref_raw = ask_opcion(["Auto (codium > code)", "VSCodium (codium)", "VS Code (code)", "Solo generar"], "IDE")
            pref = {"Auto (codium > code)": "auto", "VSCodium (codium)": "codium", "VS Code (code)": "vscode", "Solo generar": "auto"}.get(pref_raw, "auto")
            generar_vscode(salida, mapping, ide=pref, instalar=pref_raw != "Solo generar")
    print("\nArchivos creados:")
    for f in [
        "docker-compose.yml",
        "config/odoo.conf",
        ".env",
        "README.md",
        ".gitignore",
        "AGENTS.md",
        "addons/custom/.gitkeep",
        "addons/oca/.gitkeep",
        "addons/adhoc/.gitkeep",
        "addons/cybrosys/.gitkeep",
        "addons/mates/.gitkeep",
        "addons/codize/.gitkeep",
        "addons/extras/.gitkeep",
        "addons/repos.json",
        "odoo-addons.py",
        "addons-bundle.ejemplo.json",
    ] + creados_extra:
        print(f"  - {f}")
    print("\nSiguiente paso:")
    print(f"  cd {salida} && docker compose up -d")
    print(f"  Abrir http://localhost:{puerto}")
    # --- Localización vía flag (el menú interactivo de localización se quitó;
    #     usar opción 9 para AdHoc en proyecto existente, o módulos manual) ---
    if args.localizacion:
        aplicar_localizacion(salida, version, args.localizacion,
                             ofrecer_aplicar=False)
    # --- Paso addons (bundle automático > directos > interactivo; rama version.0, no se pregunta) ---
    if args.bundle is not None:
        print(f"\nBundle automático: {args.bundle} (rama {version}.0 automática) ...")
        instalar_bundle(salida, args.bundle, version)
    elif args.addon:
        print(
            f"\nInstalando {len(args.addon)} addon(s) directo(s) (rama {version}.0 automática) ..."
        )
        for spec in args.addon:
            org, repo, modulos = parse_addon_spec(spec)
            if not modulos:
                print(f"  ⚠ spec sin módulos: {spec} (formato org/repo:mod1,mod2)")
                continue
            instalar_addon(salida, org, repo, modulos, version)
    elif not args.sin_addons and not args.no_input and es_interactivo():
        # La descarga de módulos se hace desde el menú (opción 2 sync,
        # opción 3 localización): el crear solo deja el proyecto listo y vuelve al menú.
        print("\nMódulos: no se descargan acá.")
        print("  Siguiente: menú opción 2 (sync: bundle/lista + deps + rebuild)")
        print("  y opción 3 (localización AR si la necesitas).")
    else:
        print("\nAddons (sparse, solo módulos elegidos):")
        print(
            "  Plantilla todo-junto: cp addons-bundle.ejemplo.json addons-bundle.json, llénala y:"
        )
        print(
            f"  cd {salida} && omc addons bundle addons-bundle.json --odoo {version}"
        )
        print(
            f"  Manual: cd {salida} && omc addons add --repo server-tools --org oca --odoo {version}"
        )
    # --- Bundle exportable: fusiona lo instalado en addons-bundle.json ---
    if actualizar_bundle_desde_estado(salida):
        print("  ✓ addons-bundle.json actualizado para replicar la instancia.")
    # --- Conf de módulos especiales (ej queue_job -> odoo.conf) ---
    asegurar_queue_job_conf(salida, args)
    # --- Dependencias internas: reporte y oferta de traer faltantes (mismo-repo/catálogo/tu org) ---
    hay_addons = (
        bool(args.addon or args.bundle is not None)
        or (salida / "addons" / "repos.json").exists()
        and (salida / "addons" / "repos.json").read_text().strip() not in ("", "[]")
    )
    if not hay_addons:
        print("\n(Sin módulos de terceros: no hay dependencias internas que resolver.)")
    else:
        from types import SimpleNamespace as _NS
        # Reporte en VIVO usando llamadas directas (sin subprocess)
        try:
            run_deps(_NS(proyecto=str(salida), fix=False, porcelain=False, enfocar="", branch="", odoo=""))
            # Verificar si hay pendientes via porcelain (captura)
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                run_deps(_NS(proyecto=str(salida), fix=False, porcelain=True, enfocar="", branch="", odoo=""))
            q_out = buf.getvalue()
            traer = False
            if "Todo resuelto." not in q_out and "TODO_RESUELTO" not in q_out:
                traer = (
                    args.deploy
                    or args.no_input
                    or (
                        es_interactivo()
                        and preguntar(
                            "¿Traer dependencias internas faltantes?",
                            "si",
                            ["si", "no"],
                        )
                        == "si"
                    )
                )
            if traer:
                if not gh_token() and not gh_org():
                    print(
                        "  (Tip: menú 8 configura token/org para privados, tu org y más cuota.)"
                    )
                run_deps(_NS(proyecto=str(salida), fix=True, porcelain=False, enfocar="", branch="", odoo=""))
        except SystemExit:
            print("  ⚠ deps falló; sigue igual.")
        except Exception as _e:  # noqa: BLE001
            print(f"  ⚠ deps error: {_e}")
    # --- Dependencias externas + despliegue final ---
    # Deps: siempre que haya addons directos/bundle o modo interactivo o --deploy; en --no-input puro se omite
    # paso_dependencias devuelve True si ya resolvió el deploy (pregunta única) -> no repetir
    deploy_hecho = False
    if args.deploy or hay_addons or not args.no_input:
        deploy_hecho = bool(
            paso_dependencias(
                salida, mapping, auto=args.deploy or args.no_input, puerto=puerto
            )
        )
    if not args.sin_deploy and not deploy_hecho:
        paso_despliegue(salida, puerto, auto=args.deploy)
