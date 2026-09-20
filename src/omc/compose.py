"""Generación de docker-compose.yml, odoo.conf, Dockerfile y bloques auxiliares."""
from pathlib import Path

from .core import leer_env, render, sin_renderizar, template_text

PROXY_NETWORK = "omc-proxy"
PROXY_PROJECT = "proxy"


def generar_proxy_compose() -> str:
    """docker-compose.yml del proxy central (sin placeholders pendientes)."""
    return render(template_text("proxy-compose.yml.tpl"), {"PROYECTO": PROXY_PROJECT})


def generar_compose(entorno: str, mapping: dict) -> str:
    tpl = "docker-compose.dev.yml.tpl" if entorno == "desarrollo" else "docker-compose.prod.yml.tpl"
    return render(template_text(tpl), mapping)


def generar_odoo_conf(entorno: str, mapping: dict) -> str:
    dev = entorno == "desarrollo"
    m = dict(mapping)
    m["WORKERS"] = "0" if dev else mapping.get("ODOO_WORKERS", "4")
    if dev:
        m["EXTRA_OPCIONES"] = "; dev: sin workers, recarga activa con --dev=all"
    else:
        # Límites escalados a los recursos (vienen del reparto; fallback = defaults Odoo)
        m["EXTRA_OPCIONES"] = (
            "gevent_port = 8072\n"
            f"limit_memory_hard = {m.get('ODOO_LIMIT_HARD', '2684354560')}\n"
            f"limit_memory_soft = {m.get('ODOO_LIMIT_SOFT', '2147483648')}\n"
            "limit_request = 8192\n"
            "limit_time_cpu = 600\n"
            "limit_time_real = 1200"
        )
        if mapping.get("NGINX") == "si":
            # Detrás de nginx: Odoo debe confiar en X-Forwarded-Proto
            m["EXTRA_OPCIONES"] += "\nproxy_mode = True"
    return render(template_text("odoo.conf.tpl"), m)


def parchear_compose_a_build(salida: Path, mapping: dict):
    """Cambia odoo: image: X -> build: . + image: proyecto-odoo:ver. Idempotente."""
    f = Path(salida) / "docker-compose.yml"
    txt = f.read_text(encoding="utf-8")
    if "build: ." in txt:
        return False
    img = mapping["ODOO_IMAGE"]
    txt = txt.replace(f"    image: {img}",
                      f"    build: .\n    image: {mapping['PROYECTO'].lower()}-odoo:{mapping['ODOO_VERSION']}",
                      1)
    f.write_text(txt, encoding="utf-8")
    return True


def asegurar_proxy_mode(salida) -> bool:
    """Agrega proxy_mode = True a config/odoo.conf si falta. Devuelve si cambió."""
    f = Path(salida) / "config" / "odoo.conf"
    if not f.exists():
        return False
    txt = f.read_text(encoding="utf-8")
    if "proxy_mode" in txt:
        return False
    f.write_text(txt.rstrip("\n") + "\nproxy_mode = True\n", encoding="utf-8")
    return True


def parchear_compose_a_proxy(salida, proyecto: str) -> dict:
    """Conecta un proyecto al proxy central. Idempotente y puro en texto.

    - Rechaza (SystemExit) si el proyecto tiene nginx local: un solo publicador
      80/443 por host (quitar el bloque o usar modo standalone).
    - odoo: container_name <proyecto>-odoo (DNS estable entre composes),
      networks default + omc-proxy (externa), ports -> expose.
    - Agrega el bloque networks/omc-proxy externa al final si falta.
    Devuelve {"cambios": [...]} con lo aplicado.
    """
    salida = Path(salida).resolve()
    f = salida / "docker-compose.yml"
    txt = f.read_text(encoding="utf-8")
    if "\n  nginx:" in txt:
        import sys as _sys
        _sys.exit(
            f"{salida.name} ya tiene nginx local (publica 80/443). "
            "Para el proxy central: quitá los servicios nginx:/certbot: del "
            "docker-compose.yml o usá el modo standalone."
        )
    cambios = []
    cname = f"{proyecto.lower()}-odoo"
    # container_name justo después de "  odoo:"
    if f"container_name: {cname}" not in txt:
        txt = txt.replace("  odoo:\n", f"  odoo:\n    container_name: {cname}\n", 1)
        cambios.append("container_name")
    # networks del servicio odoo (anclado al container_name recién insertado)
    if PROXY_NETWORK not in txt.split("volumes:", 1)[0].rsplit("  odoo:", 1)[-1]:
        anchor = f"    container_name: {cname}\n"
        txt = txt.replace(
            anchor,
            anchor + "    networks:\n      - default\n      - omc-proxy\n",
            1,
        )
        cambios.append("networks odoo")
    # ports -> expose (el proxy llega por red, no por puertos publicados)
    env = leer_env(salida)
    puerto = env.get("ODOO_PORT", "8069")
    if f'    ports:\n      - "{puerto}:8069"\n' in txt:
        txt = txt.replace(
            f'    ports:\n      - "{puerto}:8069"\n',
            '    expose:\n      - "8069"\n      - "8072"\n',
            1,
        )
        cambios.append("expose")
    # bloque networks top-level antes de volumes (chequeo independiente del
    # servicio odoo: la inserción de arriba ya menciona omc-proxy en el texto):
    if "omc-proxy:\n    external: true" not in txt:
        if "\nvolumes:" in txt:
            txt = txt.replace(
                "\nvolumes:",
                "\nnetworks:\n  omc-proxy:\n    external: true\nvolumes:",
                1,
            )
        else:
            txt = txt.rstrip("\n") + "\nnetworks:\n  omc-proxy:\n    external: true\n"
        cambios.append("networks externa")
    if sin_renderizar(txt):
        import sys as _sys
        _sys.exit(f"{f} quedó con placeholders sin renderizar: {sin_renderizar(txt)}")
    f.write_text(txt, encoding="utf-8")
    return {"cambios": cambios}
