"""Migración de proyectos Odoo entre versiones (herramientas OCA).

Flujo autoguiado en dos etapas:

1. Código: para cada módulo del origen se verifica si ya existe migrado
   a la versión destino (rama X.0 en OCA/AdHoc/...). Si no, se ofrece
   migrarlo con ``odoo-module-migrator`` (solo código, no toca datos).
2. Base de datos: se clona ``OCA/OpenUpgrade`` (rama = versión destino,
   NO es pip), se instala ``openupgradelib`` (pip) y se genera el script
   de migración (``--update all --stop-after-init``).

OpenUpgrade exige pasar por cada versión intermedia (17->19 = 17->18->19).
"""
import shutil
import subprocess
import sys
from pathlib import Path

from .core import (
    cargar_catalogo,
    cargar_versions,
    find_proyecto,
    leer_env,
    odoo_to_branch,
    render,
    template_text,
)
from .github import resolve_repo
from .gitutils import git_clone, ramas_version
from .manifest import (
    iterar_modulos,
    leer_manifest,
    load_repos,
    save_repos,
)
from .tui import (
    ask_si_no,
    ask_texto,
    es_interactivo,
)

OPENUPGRADE_URL = "https://github.com/OCA/OpenUpgrade"

# Herramientas OCA que se ofrecen instalar con pip si faltan:
# (binario en PATH o módulo importable, paquete pip, para qué etapa es)
HERRAMIENTA_MIGRADOR = {"binario": "odoo-module-migrate", "paquete": "odoo-module-migrator",
                        "para": "migrar código de módulos"}
HERRAMIENTA_LIB = {"modulo": "openupgradelib", "paquete": "openupgradelib",
                   "para": "migración de BD con OpenUpgrade"}

# Caché en memoria: url -> ramas X.0 | None (evita un ls-remote por módulo).
_RAMAS_CACHE: dict = {}


def _ramas(url: str):
    """Ramas X.0 del remoto con caché en memoria."""
    if url not in _RAMAS_CACHE:
        try:
            _RAMAS_CACHE[url] = ramas_version(url)
        except Exception:  # noqa: BLE001 - sin red => desconocido
            _RAMAS_CACHE[url] = None
    return _RAMAS_CACHE[url]


def _hay_binario(nombre: str) -> bool:
    return shutil.which(nombre) is not None


def _hay_modulo(nombre: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(nombre) is not None
    except Exception:  # noqa: BLE001
        return False


def _pip_instalar(paquete: str) -> tuple:
    """pip install con el intérprete actual. Devuelve (ok, error_corto)."""
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", paquete],
                       text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       timeout=300)
    return r.returncode == 0, (r.stderr or "")[-800:]


def asegurar_paquete_oca(herramienta: dict, args=None) -> bool:
    """Garantiza la herramienta OCA: si falta, ofrece instalarla con pip.

    Interactivo: pregunta. No interactivo con --yes: instala directo.
    No interactivo sin --yes: avisa y devuelve False (el llamador omite la etapa).
    """
    paquete = herramienta["paquete"]
    presente = (_hay_binario(herramienta["binario"]) if herramienta.get("binario")
                else _hay_modulo(herramienta["modulo"]))
    if presente:
        return True
    print(f"\n  Falta {paquete} ({herramienta['para']}).")
    instalar = False
    if es_interactivo():
        instalar = ask_si_no(f"¿Instalar {paquete} con pip ahora?", default_no=False)
    elif args is not None and getattr(args, "yes", False):
        print(f"  (--yes: instalando {paquete} ...)")
        instalar = True
    if not instalar:
        print(f"  (omitido: a mano con `pip install {paquete}`)")
        return False
    ok, err = _pip_instalar(paquete)
    if not ok:
        print(f"  ⚠ pip falló: {err}")
        return False
    presente = (_hay_binario(herramienta["binario"]) if herramienta.get("binario")
                else _hay_modulo(herramienta["modulo"]))
    if not presente:
        print(f"  ⚠ Se instaló pero no aparece ({paquete}). Revisa tu PATH/venv.")
        return False
    print(f"  ✓ {paquete} listo.")
    return True


def listar_modulos_instalados(proyecto: Path) -> list:
    """[{name, repo, org, path, branch}] desde repos.json + custom/ + extras/."""
    proyecto = Path(proyecto).resolve()
    env = leer_env(proyecto)
    branch_actual = odoo_to_branch(env.get("ODOO_VERSION", "")) if env.get("ODOO_VERSION") else ""
    mods = []
    vistos = set()
    for r in load_repos(proyecto):
        for m in r.get("modules", []) or []:
            if m in vistos:
                continue
            vistos.add(m)
            mods.append({
                "name": m,
                "repo": r.get("repo", ""),
                "org": r.get("org", ""),
                "url": r.get("url", ""),
                "path": str(proyecto / r.get("path", "")),
                "branch": r.get("branch", branch_actual),
            })
    for sub in ("addons/custom", "addons/extras"):
        base = proyecto / sub
        if not base.is_dir():
            continue
        for name, path in iterar_modulos(base):
            if name in vistos:
                continue
            vistos.add(name)
            man = leer_manifest(path)
            mods.append({
                "name": name,
                "repo": name,
                "org": "custom",
                "url": "",
                "path": str(path),
                "branch": branch_actual,
                "version_manifest": man.get("version", ""),
            })
    return sorted(mods, key=lambda x: x["name"])


def check_module_migrated(mod_name: str, org: str, repo: str, source_ver: str,
                          target_ver: str, url: str = "") -> dict:
    """¿Existe el módulo migrado a la versión destino?

    Devuelve {migrated: bool, branch: str, repo_url: str, motivo: str}.
    migrated=False también para módulos custom (no hay upstream que mirar).
    """
    branch = odoo_to_branch(target_ver)
    if (org or "").lower() == "custom" or (not repo and not url):
        return {"migrated": False, "branch": branch, "repo_url": url or "",
                "motivo": "custom (código propio, sin upstream)"}
    catalogo = cargar_catalogo()
    try:
        _org, _repo, repo_url = resolve_repo(org or "oca", repo or mod_name, url or "", catalogo)
    except Exception:  # noqa: BLE001
        repo_url = url or ""
    if not repo_url:
        return {"migrated": False, "branch": branch, "repo_url": "",
                "motivo": "sin URL de repo conocida"}
    ramas = _ramas(repo_url)
    if ramas is None:
        return {"migrated": False, "branch": branch, "repo_url": repo_url,
                "motivo": "no se pudo leer el remoto (¿sin red o privado?)"}
    if branch in ramas:
        return {"migrated": True, "branch": branch, "repo_url": repo_url,
                "motivo": f"rama {branch} disponible upstream"}
    hay = ", ".join(ramas) if ramas else "(ninguna X.0)"
    return {"migrated": False, "branch": branch, "repo_url": repo_url,
            "motivo": f"sin rama {branch} (tiene: {hay})"}


def verificar_migrabilidad(proyecto: Path, source_ver: str, target_ver: str) -> dict:
    """Clasifica cada módulo: migrados / sin_migrar / custom. Muestra progreso."""
    proyecto = Path(proyecto).resolve()
    mods = listar_modulos_instalados(proyecto)
    print(f"\nVerificando {len(mods)} módulos: {source_ver}.0 -> {target_ver}.0 ...")
    migrados, sin_migrar, custom = [], [], []
    for m in mods:
        r = check_module_migrated(m["name"], m.get("org", ""), m.get("repo", ""),
                                  source_ver, target_ver, m.get("url", ""))
        m["check"] = r
        marca = "✓" if r["migrated"] else ("~" if m.get("org") == "custom" else "✗")
        print(f"  {marca} {m['name']:40} {r['motivo']}")
        if r["migrated"]:
            migrados.append(m)
        elif (m.get("org") or "").lower() == "custom":
            custom.append(m)
        else:
            sin_migrar.append(m)
    print(f"\nResumen: {len(migrados)} migrados upstream, "
          f"{len(sin_migrar)} sin migrar, {len(custom)} custom, total {len(mods)}.")
    return {"migrados": migrados, "sin_migrar": sin_migrar, "custom": custom,
            "total": len(mods)}


def setup_openupgrade(proyecto: Path, target_ver: str) -> bool:
    """Clona OCA/OpenUpgrade rama destino (sparse: framework + scripts)."""
    proyecto = Path(proyecto).resolve()
    branch = odoo_to_branch(target_ver)
    dest = proyecto / "addons" / "openupgrade"
    print(f"\nClonando OpenUpgrade@{branch} -> {dest} ...")
    try:
        if not dest.is_dir():
            git_clone(OPENUPGRADE_URL, branch, str(dest))
        r = subprocess.run(["git", "sparse-checkout", "set",
                            "openupgrade_framework", "openupgrade_scripts"],
                           cwd=str(dest), text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        if r.returncode != 0:
            print(f"  ⚠ sparse-checkout falló: {(r.stderr or '')[-500:]}")
            return False
    except SystemExit as e:
        print(f"  ⚠ No se pudo clonar OpenUpgrade: {e}")
        return False
    repos = load_repos(proyecto)
    if not any(x.get("path") == "addons/openupgrade" for x in repos):
        repos.append({"org": "oca", "repo": "OpenUpgrade", "url": OPENUPGRADE_URL,
                      "branch": branch, "path": "addons/openupgrade",
                      "modules": ["openupgrade_framework", "openupgrade_scripts"]})
        save_repos(proyecto, repos)
    try:
        from .addonsops import actualizar_addons_path
        actualizar_addons_path(proyecto)
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ No se pudo actualizar addons_path: {e}")
    print("  ✓ OpenUpgrade listo (framework + scripts).")
    return True


def setup_openupgradelib() -> bool:
    """Deja openupgradelib importable (librería helper, NO es el framework).

    Si ya está, no reinstala. Si falta, instala por pip (el consentimiento lo da
    la pregunta previa "¿Preparar OpenUpgrade...?" del flujo).
    """
    if _hay_modulo("openupgradelib"):
        print("  ✓ openupgradelib ya disponible.")
        return True
    print("\nInstalando openupgradelib (pip) ...")
    ok, err = _pip_instalar("openupgradelib")
    if not ok:
        print(f"  ⚠ pip falló: {err}")
        return False
    if not _hay_modulo("openupgradelib"):
        print("  ⚠ Se instaló pero no se puede importar.")
        return False
    print("  ✓ openupgradelib importable.")
    return True


def migrar_codigo_modulos(proyecto: Path, modules: list, source_ver: str,
                          target_ver: str, args=None) -> dict:
    """Migra código con odoo-module-migrator sobre COPIAS en migracion/.

    Nunca muta el proyecto: trabaja en <proyecto>/migracion/<mod>/ y deja
    el resultado para revisión (git diff). Si falta el migrador, ofrece
    instalarlo con pip (asegurar_paquete_oca).
    """
    proyecto = Path(proyecto).resolve()
    if not asegurar_paquete_oca(HERRAMIENTA_MIGRADOR, args):
        return {"exitosos": [], "fallidos": [m["name"] for m in modules],
                "omitidos": [], "motivo": "odoo-module-migrate no instalado"}
    work_base = proyecto / "migracion"
    work_base.mkdir(exist_ok=True)
    exitosos, fallidos, omitidos = [], [], []
    for m in modules:
        origen = Path(m.get("path", ""))
        if not origen.is_dir():
            print(f"  ⚠ {m['name']}: no está en disco ({origen}), omitido.")
            omitidos.append(m["name"])
            continue
        work = work_base / m["name"]
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)
        try:
            shutil.copytree(origen, work)
        except OSError as e:
            print(f"  ⚠ {m['name']}: no se pudo copiar: {e}")
            fallidos.append(m["name"])
            continue
        print(f"\n  Migrando código {m['name']}: {source_ver} -> {target_ver} ...")
        r = subprocess.run(["odoo-module-migrate", "--directory", str(work),
                            "--modules", m["name"],
                            "--init-version-name", f"{source_ver}.0",
                            "--target-version-name", f"{target_ver}.0"],
                           text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=600)
        print((r.stdout or "")[-1500:])
        if r.returncode == 0:
            print(f"  ✓ {m['name']} migrado en {work} (revisar diff antes de usar).")
            exitosos.append(m["name"])
        else:
            print(f"  ⚠ {m['name']}: el migrador devolvió error (revisar arriba).")
            fallidos.append(m["name"])
    print(f"\nCódigo: {len(exitosos)} ok, {len(fallidos)} con error, "
          f"{len(omitidos)} omitidos. Resultados en {work_base}/")
    return {"exitosos": exitosos, "fallidos": fallidos, "omitidos": omitidos}


def generar_compose_migracion(proyecto: Path, target_ver: str) -> Path:
    """Genera docker-compose.migrate.yml con la imagen Odoo destino.

    Sin esto la migración correría con los binarios de la versión origen
    (el compose base) y no migraría nada entre versiones.
    """
    proyecto = Path(proyecto).resolve()
    try:
        imagen = cargar_versions().get(target_ver, {}).get("odoo", f"odoo:{target_ver}")
    except Exception:  # noqa: BLE001 - sin versions/*.env
        imagen = f"odoo:{target_ver}"
    out = proyecto / "docker-compose.migrate.yml"
    out.write_text(render(template_text("compose-migrate.yml.tpl"), {
        "PROYECTO": proyecto.name,
        "ODOO_VERSION_DESTINO": target_ver,
        "ODOO_IMAGE_DESTINO": imagen,
    }), encoding="utf-8")
    print(f"  ✓ Override generado: {out} (imagen {imagen})")
    return out


def generar_script_migracion_bd(proyecto: Path, db_name: str, target_ver: str) -> Path:
    """Genera scripts/migrate_db.sh (backup + update con openupgrade_framework).

    Corre con el override docker-compose.migrate.yml para usar los binarios
    de la versión destino (OpenUpgrade lo exige).
    """
    proyecto = Path(proyecto).resolve()
    branch = odoo_to_branch(target_ver)
    out = proyecto / "scripts" / "migrate_db.sh"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "#!/bin/bash\n"
        f"# Migración BD a Odoo {target_ver} con OpenUpgrade (rama {branch}).\n"
        "# Generado por omc. Revisar antes de ejecutar.\n"
        "# Usa el override docker-compose.migrate.yml (binarios destino).\n"
        "set -e\n"
        f'DB="${{1:-{db_name}}}"\n'
        'echo "== Backup previo =="\n'
        './scripts/backup.sh "$DB"\n'
        'echo "== Migración OpenUpgrade =="\n'
        'docker compose -f docker-compose.yml -f docker-compose.migrate.yml run --rm odoo -- \\\n'
        '  --database "$DB" \\\n'
        '  --update all --stop-after-init \\\n'
        "  --load=base,web,openupgrade_framework\n"
        'echo "OK: $DB migrada. Levantar normal: docker compose up -d"\n',
        encoding="utf-8",
    )
    try:
        out.chmod(0o755)
    except OSError:
        pass
    print(f"  ✓ Script generado: {out}")
    return out


def _pasos_intermedios(source_ver: str, target_ver: str) -> list:
    """Versiones intermedias que exige OpenUpgrade (solo saltos hacia adelante)."""
    try:
        ini, fin = int(source_ver), int(target_ver)
    except ValueError:
        return [target_ver]
    if fin <= ini:
        return []
    disp = []
    try:
        disp = [int(v) for v in cargar_versions().keys()]
    except Exception:  # noqa: BLE001
        pass
    pasos = [str(v) for v in range(ini + 1, fin + 1)]
    if disp:
        pasos = [p for p in pasos if int(p) in disp]
    return pasos


def flujo_migracion(proyecto=None, args=None) -> None:
    """Orquestador autoguiado: módulos -> código -> OpenUpgrade -> script BD."""
    g = lambda name, dflt=None: getattr(args, name, dflt) if args is not None else dflt
    proyecto = Path(proyecto).resolve() if proyecto else find_proyecto(g("proyecto"))
    env = leer_env(proyecto)
    origen = g("origen") or env.get("ODOO_VERSION", "")
    if not origen:
        sys.exit(f"No pude leer ODOO_VERSION en {proyecto}/.env (usa --origen).")
    destino = g("destino")
    if not destino and es_interactivo():
        destino = ask_texto(f"Versión destino (origen {origen})", str(int(origen) + 1))
    if not destino:
        sys.exit("Falta versión destino (usa --destino).")
    if destino == origen:
        sys.exit("Origen y destino son iguales, nada que migrar.")
    print(f"\n=== Migración {proyecto.name}: Odoo {origen} -> {destino} ===")
    pasos = _pasos_intermedios(origen, destino)
    if len(pasos) > 1:
        print(f"  OpenUpgrade exige pasar por cada versión: {' -> '.join([origen] + pasos)}")
        if es_interactivo() and not ask_si_no(
                f"¿Empezar por el primer salto ({origen} -> {pasos[0]})?", default_no=False):
            return
        destino = pasos[0]
        print(f"  Alcance de esta corrida: {origen} -> {destino}.")

    reporte = verificar_migrabilidad(proyecto, origen, destino)
    pendientes = reporte["sin_migrar"] + reporte["custom"]

    sin_codigo = bool(g("sin_codigo"))
    if pendientes and not sin_codigo:
        print(f"\n{len(pendientes)} módulos sin upstream migrado "
              f"({len(reporte['sin_migrar'])} de repos + {len(reporte['custom'])} custom).")
        if (not es_interactivo() and g("yes")) or (
                es_interactivo() and ask_si_no(
                    "¿Migrar su código con odoo-module-migrator (copias en migracion/)?",
                    default_no=False)):
            migrar_codigo_modulos(proyecto, pendientes, origen, destino, args)
        else:
            print("  (omitido: migrar el código a mano antes de la BD.)")
    elif not pendientes:
        print("\nTodo el código ya existe upstream en la versión destino. ✓")

    if es_interactivo():
        if not ask_si_no("¿Preparar OpenUpgrade (clonar framework + pip openupgradelib)?",
                         default_no=False):
            print("  (sin OpenUpgrade no hay migración de BD.)")
            return
    ok_fw = setup_openupgrade(proyecto, destino)
    ok_lib = setup_openupgradelib()
    if not (ok_fw and ok_lib):
        print("  ⚠ Faltó framework o librería; la BD no se puede migrar aún.")
        return

    sin_bd = bool(g("sin_bd"))
    if sin_bd:
        print("  (--sin-bd: no se genera script de BD.)")
        return
    bd = g("db") or ""
    if not bd and es_interactivo():
        bd = ask_texto("Base a migrar (vacío = solo generar script)", "")
    generar_compose_migracion(proyecto, destino)
    script = generar_script_migracion_bd(proyecto, bd or "<BD>", destino)
    print("\n=== Migración preparada ===")
    print(f"  Código: revisa {proyecto}/migracion/ (diff antes de usar).")
    print(f"  BD: {script} {' '.join([bd]) if bd else '<BD>'}")
    if bd and es_interactivo() and ask_si_no(
            f"¿Ejecutar la migración de '{bd}' AHORA? (ya hay backup previo)", default_no=True):
        r = subprocess.run(["bash", str(script), bd], cwd=str(proyecto))
        if r.returncode == 0:
            print(f"✓ BD '{bd}' migrada a Odoo {destino}.")
        else:
            print("⚠ Falló la migración. Revisa el log de arriba y reintenta.")
