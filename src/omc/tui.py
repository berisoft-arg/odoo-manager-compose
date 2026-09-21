"""Entrada interactiva unificada (librería ask_*) + color sutil de terminal.

Toda pregunta al usuario pasa por acá: una sola puerta por tipo de dato,
defaults seguros sin tty y sin reventar ante basura o EOF.

Color: solo si la salida es tty, sin NO_COLOR y con TERM útil. En cualquier
otro caso (tests, pipes, cron, --json) sale texto plano, byte-idéntico.
"""
import os
import sys

# Paleta OMC: solo Azul marino, blanco y gris (+ negrita). Todo lo demás es texto plano.
_NEGRITA = "1"
_AZUL_MARINO = "34"
_BLANCO = "37"
_GRIS = "90"
_FONDO_AZUL = "44"
_FIN = "0"
_ANCHO_BARRA = 60
# Alias para compatibilidad (no usados, mantenidos por si se importan)
_ROJO = _BLANCO
_VERDE = _BLANCO
_AMARILLO = _GRIS
_MAGENTA = _BLANCO
_CIAN = _AZUL_MARINO
_TENUE = _GRIS


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
    return c(texto, _NEGRITA, _BLANCO)


def numero(texto: str) -> str:
    """Números de opción del menú (con su espacio inicial adentro)."""
    return c(texto, _NEGRITA, _AZUL_MARINO)


def tenue(texto: str) -> str:
    """Texto secundario (salir, tips)."""
    return c(texto, _GRIS)


def texto_menu(texto: str) -> str:
    """Texto de opción del menú (siempre negrita)."""
    return c(texto, _NEGRITA, _BLANCO)


def ok(texto: str) -> str:
    """Éxitos (✓)."""
    return c(texto, _BLANCO)


def warn(texto: str) -> str:
    """Avisos (⚠)."""
    return c(texto, _GRIS)


def err(texto: str) -> str:
    """Errores (✗)."""
    return c(texto, _NEGRITA, _BLANCO)


def separador() -> str:
    """Línea divisoria estilo installer (gris con color, invisible sin él)."""
    return c("=" * _ANCHO_BARRA, _GRIS)


def seccion(texto: str) -> str:
    """Encabezado de sección: barra + título (reemplaza los '== ... ==')."""
    return f"{separador()}\n{titulo(texto)}"


def _ancho_visible(texto: str) -> int:
    """Ancho sin contar códigos ANSI (asume caracteres de ancho 1)."""
    import re
    return len(re.sub(r"\033\[[0-9;]*m", "", texto))


def marco(titulo_txt: str, contenido: list, pie: str = None) -> str:
    """Caja estilo installer sobre el scroll (no limpia pantalla).

    Sin color: líneas planas, byte-idénticas al formato histórico.
    """
    if not usa_color():
        partes = [titulo_txt, *contenido]
        if pie is not None:
            partes.append(pie)
        return "\n".join(partes)
    ancho = max([_ancho_visible(titulo_txt)] +
                [_ancho_visible(t) for t in contenido] +
                [_ancho_visible(pie or "")]) + 4
    borde = c("┌" + "─" * ancho + "┐", _GRIS)
    base = c("└" + "─" * ancho + "┘", _GRIS)
    li = c("│", _GRIS)
    ld = c("│", _GRIS)

    def _fila(texto: str) -> str:
        rel = _ancho_visible(texto)
        return f"{li} {texto}{' ' * max(0, ancho - rel - 2)}{ld}"

    filas = [_fila(c(f" {titulo_txt} ", _NEGRITA, _BLANCO, _FONDO_AZUL))]
    filas += [_fila(t) for t in contenido]
    if pie is not None:
        filas.append(_fila(tenue(pie)))
    return "\n".join([borde] + filas + [base])


def banner_omc(version: str) -> str:
    """Banner de arranque estilo generador (arte ASCII + nombre + versión).

    Sin color: una sola línea, igual que siempre (con línea en blanco previa).
    """
    if not usa_color():
        return f"\n=== Odoo Manager Compose {version} ==="
    arte = [
        " ██████╗ ███╗   ███╗ ██████╗",
        " ██╔══██╗████╗ ████║██╔════╝",
        " ██║  ██║██╔████╔██║██║     ",
        " ██║  ██║██║╚██╔╝██║██║     ",
        " ╚██████╔╝██║ ╚═╝ ██║╚██████╗",
        "  ╚═════╝ ╚═╝     ╚═╝ ╚═════╝",
    ]
    lineas = [c(l, _NEGRITA, _BLANCO) for l in arte]
    lineas.append(titulo(f"=== Odoo Manager Compose {version} ==="))
    return "\n" + "\n".join(lineas)


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
