"""Generación de docker-compose.yml, odoo.conf, Dockerfile y bloques auxiliares."""
from pathlib import Path

from .core import render, template_text


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
