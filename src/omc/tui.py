"""Entrada interactiva unificada (librería ask_*) + color sutil de terminal.

Toda pregunta al usuario pasa por acá: una sola puerta por tipo de dato,
defaults seguros sin tty y sin reventar ante basura o EOF.

Color: solo si la salida es tty, sin NO_COLOR y con TERM útil. En cualquier
otro caso (tests, pipes, cron, --json) sale texto plano, byte-idéntico.
"""
import os
import sys

# Paleta sutil (familia del monitor web): texto normal siempre, color en claves.
_NEGRITA = "1"
_TENUE = "2"
_ROJO = "31"
_VERDE = "32"
_AMARILLO = "33"
_MAGENTA = "35"
_CIAN = "36"
_FIN = "0"


def usa_color() -> bool:
    """True solo si tiene sentido pintar (tty real, sin NO_COLOR, TERM útil)."""
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    try:
        return sys.stdout.isatty()
    except Exception:  # noqa: BLE001
        return False


def c(texto: str, *estilos: str) -> str:
    """Envuelve en códigos ANSI solo si usa_color(); si no, texto pelado."""
    if not estilos or not usa_color():
        return texto
    return f"\033[{';'.join(estilos)}m{texto}\033[{_FIN}m"


def titulo(texto: str) -> str:
    """Encabezados (banner, secciones == ... ==)."""
    return c(texto, _NEGRITA, _MAGENTA)


def numero(texto: str) -> str:
    """Números de opción del menú (con su espacio inicial adentro)."""
    return c(texto, _CIAN)


def tenue(texto: str) -> str:
    """Texto secundario (salir, tips)."""
    return c(texto, _TENUE)


def ok(texto: str) -> str:
    """Éxitos (✓)."""
    return c(texto, _VERDE)


def warn(texto: str) -> str:
    """Avisos (⚠)."""
    return c(texto, _AMARILLO)


def err(texto: str) -> str:
    """Errores (✗)."""
    return c(texto, _ROJO)


def es_interactivo() -> bool:
    return sys.stdin.isatty()


def _leer(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def ask_texto(prompt: str, default: str = "") -> str:
    """Texto libre con default. No interactivo/EOF -> default."""
    if not es_interactivo():
        return default
    r = _leer(f"{prompt} [{default}]: ") if default else _leer(f"{prompt}: ")
    return r if r else default


def ask_opcion(prompt: str, opciones: list, default=None, aliases: dict = None) -> str:
    """Menú numerado. Acepta número, valor o alias. default = valor."""
    if default is None:
        default = opciones[-1] if opciones else ""
    if not es_interactivo():
        return default
    aliases = aliases or {}
    print(f"\n{prompt}")
    for i, op in enumerate(opciones, 1):
        print(f"  {i}) {op}")
    while True:
        r = _leer(f"Elige [1-{len(opciones)}] (default {default}): ")
        if not r:
            return default
        if r.isdigit() and 1 <= int(r) <= len(opciones):
            return opciones[int(r) - 1]
        if r in opciones:
            return r
        low = r.lower().replace(" ", "")
        if low in aliases:
            return aliases[low]
        print(err("  Opción no válida, intenta de nuevo."))


def ask_si_no(prompt: str, default_no: bool = True) -> bool:
    """Sí/No numerado."""
    dflt = "no" if default_no else "si"
    return ask_opcion(prompt, ["si", "no"], dflt) == "si"


def ask_puerto(prompt: str, default: int) -> int:
    """Puerto validado (1-65535), reintenta ante basura."""
    while True:
        r = ask_texto(prompt, str(default))
        try:
            p = int(r)
            if 1 <= p <= 65535:
                return p
        except (TypeError, ValueError):
            pass
        if not es_interactivo():
            return default
        print(err("  Puerto inválido (1-65535)."))


def ask_float(prompt: str, default: float) -> float:
    while True:
        r = ask_texto(prompt, str(default))
        try:
            return float(str(r).replace(",", "."))
        except (TypeError, ValueError):
            pass
        if not es_interactivo():
            return default
        print(err("  Número inválido."))


# Compat: el código viejo llamaba preguntar()/preguntar_si_no().
def preguntar(prompt: str, default: str = "", opciones=None) -> str:
    """Compat: delega en ask_*. No usar en código nuevo."""
    if opciones:
        return ask_opcion(prompt, opciones, default)
    return ask_texto(prompt, default)


def preguntar_si_no(prompt: str, default_no: bool = True) -> bool:
    """Compat: delega en ask_si_no. No usar en código nuevo."""
    return ask_si_no(prompt, default_no)
