"""CLI único: omc (menú + subcomandos)."""
import argparse
import sys
from pathlib import Path

from . import __version__
from .core import ENTORNOS
from .tui import es_interactivo


def _add_crear_args(p):
    p.add_argument("--entorno", choices=ENTORNOS)
    p.add_argument("--version", dest="version", choices=["17", "18", "19"])
    p.add_argument("--nombre", default=None)
    p.add_argument("--puerto", type=int, default=None)
    p.add_argument("--gevent-port", type=int, default=None)
    p.add_argument("--salida", default=None)
    p.add_argument("--password", default=None)
    p.add_argument("--admin-password", default=None)
    p.add_argument("--no-input", action="store_true")
    p.add_argument("--addon", action="append", default=[])
    p.add_argument("--sin-addons", action="store_true")
    p.add_argument("--bundle", nargs="?", const="addons-bundle.json", default=None)
    p.add_argument("--localizacion", default=None)
    p.add_argument("--deploy", action="store_true")
    p.add_argument("--sin-deploy", action="store_true")
    p.add_argument("--dominio", default=None)
    p.add_argument("--email", default=None)
    p.add_argument("--sin-nginx", action="store_true")
    p.add_argument("--staging", action="store_true")
    p.add_argument("--odoo-cpus", default=None)
    p.add_argument("--odoo-mem", default=None)
    p.add_argument("--db-cpus", default=None)
    p.add_argument("--db-mem", default=None)
    p.add_argument("--rclone-remote", default=None)
    p.add_argument("--vcpus", type=float, default=None)
    p.add_argument("--ram-gb", type=float, default=None)


def build_parser():
    p = argparse.ArgumentParser(prog="omc", description="Odoo Manager Compose")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd")

    # crear (default si no hay subcomando)
    c = sub.add_parser("crear", help="Crear proyecto nuevo")
    _add_crear_args(c)

    # acciones sobre proyecto existente (reusan menú)
    for name, help_text in [
        ("monitor", "Monitor web"),
        ("github", "Configurar GitHub"),
        ("backup", "Backup manual"),
        ("restore", "Restaurar BD"),
    ]:
        s = sub.add_parser(name, help=help_text)
        s.add_argument("--proyecto", default=None)

    sy = sub.add_parser("sync", help="Descargar módulos y aplicar")
    sy.add_argument("--proyecto", default=None)
    sy.add_argument("--bundle", default="")
    sy.add_argument("--odoo", default=None)
    sy.add_argument("--branch", default=None)
    sy.add_argument("--yes", action="store_true")
    sy.add_argument("--skip-install", action="store_true")
    sy.add_argument("--no-deploy", action="store_true")

    lo = sub.add_parser("localizar", help="Instalación Localización Argentina")
    lo.add_argument("--proyecto", default=None)
    lo.add_argument("--localizacion", default="argentina-adhoc")

    w = sub.add_parser("web", help="Configurar nginx+certbot")
    w.add_argument("--proyecto", default=None)
    w.add_argument("--dominio", default=None)
    w.add_argument("--email", default=None)
    w.add_argument("--staging", action="store_true")
    g = w.add_mutually_exclusive_group()
    g.add_argument("--proxy", action="store_true",
                   help="Proxy central multinstancia (default si está inicializado)")
    g.add_argument("--standalone", action="store_true",
                   help="Nginx propio del proyecto (un solo HTTPS por host)")

    r = sub.add_parser("rclone", help="Configurar rclone/Drive")
    r.add_argument("--proyecto", default=None)
    r.add_argument("--rclone-remote", default=None)

    # addons subcomandos (compat)
    a = sub.add_parser("addons", help="Operaciones addons sobre un proyecto")
    a.add_argument("subcmd", nargs=argparse.REMAINDER)

    sub.add_parser("list", help="Lista instancias (proyectos) detectadas")
    d = sub.add_parser("doctor", help="Valida compose/conf/addons por instancia")
    d.add_argument("--proyecto", default=None, help="Solo esa instancia")
    d.add_argument("--fix", action="store_true", help="Repara addons_path si hace falta")

    m = sub.add_parser("migrar", help="Migrar proyecto a nueva versión Odoo (OCA)")
    m.add_argument("--proyecto", default=None)
    m.add_argument("--origen", default=None, help="Versión origen (ej 17, default: .env)")
    m.add_argument("--destino", default=None, help="Versión destino (ej 19)")
    m.add_argument("--db", default=None, help="Base a migrar (vacío = solo generar script)")
    m.add_argument("--sin-codigo", action="store_true", help="Saltar migración de código")
    m.add_argument("--sin-bd", action="store_true", help="Saltar script de BD")
    m.add_argument("--yes", action="store_true", help="No preguntar (migra código sin confirmar)")

    px = sub.add_parser("proxy", help="Proxy multinstancia (nginx compartido)")
    px.add_argument("accion", nargs="?", default="init", choices=["init"],
                    help="Acción (default: init)")
    px.add_argument("--salida", default=None, help="Carpeta del proxy (default: <proyectos>/proxy)")

    return p


def _ejecutar_accion_menu(accion):
    """Ejecuta una acción del menú interactivo. Vuelve al llamador al terminar."""
    import types
    from types import SimpleNamespace

    if accion == "crear":
        from .flows import crear_proyecto
        # delegar a crear con args vacíos (pedirá todo)
        crear_proyecto(types.SimpleNamespace(
            entorno=None, version=None, nombre=None, puerto=None, gevent_port=None,
            salida=None, password=None, admin_password=None, no_input=False,
            addon=[], sin_addons=False, bundle=None, localizacion=None,
            deploy=False, sin_deploy=False, dominio=None, email=None, sin_nginx=False,
            staging=False, odoo_cpus=None, odoo_mem=None, db_cpus=None, db_mem=None,
            rclone_remote=None, vcpus=None, ram_gb=None, proyecto=None
        ))
        return
    # resto de acciones: monitor/github/proxy no necesitan proyecto
    if accion in ("monitor", "github", "proxy"):
        from .flows import run_monitor, run_github, run_proxy
        {"monitor": run_monitor, "github": run_github,
         "proxy": run_proxy}[accion](SimpleNamespace(proyecto=None))
        return
    # resto de acciones necesitan proyecto (se elige uno)
    # reutilizar lógica de flows.elegir_proyecto si existe
    try:
        from .flows import elegir_proyecto as _elegir
        proj = _elegir()
    except Exception:
        proj = Path.cwd()
    # ejecutar directamente según la acción elegida
    if accion == "sync":
        from .flows import run_sync
        run_sync(SimpleNamespace(bundle="", branch="", odoo="", yes=False, no_deploy=False, skip_install=False, proyecto=str(proj)))
        return
    elif accion == "localizacion":
        from .flows import aplicar_localizacion
        ver = proj.joinpath(".env").read_text().split("ODOO_VERSION=")[1].split()[0] if (proj / ".env").exists() else "18"
        aplicar_localizacion(proj, ver, "argentina-adhoc")
        return
    elif accion == "migrar":
        from .migrate import flujo_migracion
        flujo_migracion(proj, SimpleNamespace(
            proyecto=str(proj), origen=None, destino=None, db=None,
            sin_codigo=False, sin_bd=False, yes=False,
        ))
        return
    elif accion in ("web", "rclone", "backup", "restore"):
        from .flows import run_web, run_rclone, run_backup, run_restore
        {"web": run_web, "rclone": run_rclone,
         "backup": run_backup, "restore": run_restore}[accion](SimpleNamespace(proyecto=str(proj)))
        return
    else:
        print(f"Acción desconocida: {accion}")
        return


def _menu_loop():
    """Menú en loop: tras ejecutar o cancelar una acción vuelve al menú.
    Solo sale con la opción 0 (o Ctrl+C)."""
    from .flows import menu_principal

    while True:
        try:
            accion = menu_principal()
        except KeyboardInterrupt:
            print()
            return
        if accion == "salir":
            return
        try:
            _ejecutar_accion_menu(accion)
        except KeyboardInterrupt:
            print("\n(acción cancelada, vuelvo al menú)")
        except SystemExit as e:
            # sys.exit(msg) de la acción: mostrar y volver al menú, no salir
            if e.code not in (None, 0):
                print(e.code)
        except Exception as e:  # noqa: BLE001 - cualquier fallo vuelve al menú
            print(f"⚠ Falló la acción: {e}")


def main(argv=None):
    from .flows import crear_proyecto  # import tardío para evitar ciclos

    parser = build_parser()
    args, _unknown = parser.parse_known_args(argv)

    # Sin subcomando: menú interactivo clásico si hay tty, si no crear
    if not args.cmd:
        if not es_interactivo():
            # no tty: asumir crear con defaults
            # Re-parsear como crear
            import sys as _sys

            _sys.argv = ["omc", "crear"] + (_sys.argv[1:] if argv is None else list(argv or []))
            args = parser.parse_args()
            args.cmd = "crear"
        else:
            # menú en loop hasta opción 0
            _menu_loop()
            return

    if args.cmd == "crear":
        crear_proyecto(args)
    elif args.cmd == "sync":
        from .flows import run_sync
        run_sync(args)
    elif args.cmd == "localizar":
        from .flows import aplicar_localizacion
        from .core import leer_env, find_proyecto
        proj = find_proyecto(args.proyecto)
        ver = leer_env(proj).get("ODOO_VERSION", "")
        if ver not in ("17", "18", "19"):
            sys.exit(f"No pude leer ODOO_VERSION válida en {proj}/.env.")
        aplicar_localizacion(proj, ver, args.localizacion)
    elif args.cmd == "list":
        from .flows import run_list
        run_list(args)
    elif args.cmd == "doctor":
        from .flows import run_doctor
        run_doctor(args)
    elif args.cmd == "addons":
        # delegar a omc.addons_cli (propaga exit code)
        import subprocess, sys as _sys
        sys.exit(subprocess.run([_sys.executable, "-m", "omc.addons_cli"] + (args.subcmd or [])).returncode)
    elif args.cmd == "migrar":
        from .migrate import flujo_migracion
        flujo_migracion(args.proyecto, args)
    elif args.cmd == "proxy":
        from .flows import run_proxy_init
        run_proxy_init(getattr(args, "salida", None))
    elif args.cmd in ("web", "rclone", "monitor", "github", "backup", "restore"):
        from .flows import run_web, run_rclone, run_monitor, run_github, run_backup, run_restore
        {"web": run_web, "rclone": run_rclone, "monitor": run_monitor,
         "github": run_github, "backup": run_backup, "restore": run_restore}[args.cmd](args)
    else:
        print(f"Comando desconocido: {args.cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
