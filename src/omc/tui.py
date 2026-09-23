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
_SUBRAYADO = "4"
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


def marco(titulo_txt: str, contenido: list, pie: str = None,
          resaltar_titulo: bool = True) -> str:
    """Caja estilo installer sobre el scroll (no limpia pantalla).

    Sin color: líneas planas, byte-idénticas al formato histórico.
    Con resaltar_titulo=False el título va plano (sin fondo azul); solo
    la opción con foco lleva resaltado al navegar con flechas.
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

    if resaltar_titulo:
        filas = [_fila(c(f" {titulo_txt} ", _NEGRITA, _BLANCO, _FONDO_AZUL))]
    else:
        filas = [_fila(tenue(f" {titulo_txt} "))]
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


def elegir_interactivo(opciones: list, titulo_txt: str = "¿Qué quiere hacer?",
                       pie: str = None, resaltar_titulo: bool = True) -> int | None:
    """Menú navegable con flechas ↑/↓ + Enter. Retorna índice o None si sin tty.

    - Gate: sin tty real (stdin o stdout no es tty, NO_COLOR, TERM=dumb) → None (fallback numérico).
    - Con tty: modo raw cbreak, oculta cursor, pinta caja; solo la opción con
      foco lleva resaltado (fondo azul) al navegar. Sin mover flechas no hay
      nada resaltado (título siempre plano si resaltar_titulo=False).
      Enter confirma, dígito mueve selección, ESC/q sale (último = Salir).
      Restaura terminal siempre (finally).
    - Sin deps extra (solo termios/tty/select, stdlib). En Windows retorna None.
    """
    # Gate: sin tty → fallback
    if os.environ.get("NO_COLOR") is not None:
        return None
    if os.environ.get("TERM", "") == "dumb":
        return None
    try:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            return None
    except Exception:  # noqa: BLE001
        return None
    try:
        import select
        import termios
        import tty
    except Exception:  # noqa: BLE001  (Windows)
        return None

    # Construir contenido base para medir alto (sin resaltado aún)
    # El marco real se renderiza dentro del loop con resaltado
    n = len(opciones)
    if n == 0:
        return None
    idx = -1  # sin foco inicial: nada resaltado hasta mover flechas/dígito
    # Para distinguir, el llamador pasa lista completa con Salir incluido
    fd = sys.stdin.fileno()
    try:
        old = termios.tcgetattr(fd)
    except Exception:  # noqa: BLE001
        return None
    # Ocultar cursor
    try:
        sys.stdout.write("\x1b[?25l")
        sys.stdout.flush()
    except Exception:  # noqa: BLE001
        pass

    def _pinta(sel: int):
        # Renderiza caja con item sel resaltado (fondo azul)
        lineas = []
        for i, lab in enumerate(opciones):
            # lab ya viene formateado como "  1) Texto"; resaltamos toda la línea
            if i == sel:
                # Fondo azul + blanco negrita para la línea completa
                lineas.append(c(f"  {lab}", _NEGRITA, _BLANCO, _FONDO_AZUL))
            else:
                # Mantener formato original (numero azul, texto blanco)
                # Re-parsear "  1) Texto" para no perder colores previos si los trae
                # Si lab trae ANSI, respetarlo; si no, pintarlo normal
                if lab.strip().startswith("0)"):
                    lineas.append(tenue(f"  {lab.strip()}"))
                else:
                    # Separar número y resto si viene como "  1) Texto"
                    # Fallback simple: pintar como texto_menu si no tiene ANSI
                    if "\x1b[" not in lab:
                        # Intentar separar "1) Texto"
                        if ")" in lab:
                            pref = lab.split(")")[0] + ")"
                            rest = lab.split(")", 1)[1]
                        else:
                            pref = lab
                            rest = ""
                        lineas.append(f"  {numero(pref)} {texto_menu(rest)}")
                    else:
                        lineas.append(f"  {lab}")
        # Usar marco interno con contenido ya coloreado
        out = marco(titulo_txt, lineas, pie=pie, resaltar_titulo=resaltar_titulo)
        return out

    # Pintar inicialmente
    # Guardar altura para repintar in-place
    altura = 0
    try:
        tty.setcbreak(fd)
        # Primer pintado fuera del loop para calcular altura
        out = _pinta(idx)
        sys.stdout.write(out + "\n")
        sys.stdout.flush()
        altura = out.count("\n") + 1
        # También banner ya está arriba; no lo repintamos
        while True:
            # Esperar tecla sin bloquear 100% CPU (select)
            r, _, _ = select.select([sys.stdin], [], [], 0.2)
            if not r:
                continue
            ch = os.read(fd, 3)
            if not ch:
                continue
            # Flecha arriba: \x1b[A  o \x1bOA
            if ch in (b"\x1b[A", b"\x1bOA"):
                idx = n - 1 if idx == -1 else (idx - 1) % n
            elif ch in (b"\x1b[B", b"\x1bOB"):
                idx = 0 if idx == -1 else (idx + 1) % n
            elif ch in (b"\r", b"\n"):
                return idx if idx != -1 else 0
            elif ch == b"\x1b":  # ESC solo → salir
                return n - 1 if opciones[-1].strip().startswith("0)") or "Salir" in opciones[-1] else n - 1
            elif ch in (b"q", b"Q"):
                return n - 1
            elif len(ch) == 1 and 48 <= ch[0] <= 57:  # dígito 0-9
                try:
                    d = int(ch.decode())
                except Exception:  # noqa: BLE001
                    continue
                # Mapeo: 1..n-1 → idx, 0 → último (Salir)
                if d == 0:
                    idx = n - 1
                elif 1 <= d <= n - 1:
                    idx = d - 1
                else:
                    continue
            else:
                continue
            # Repintar in-place: subir cursor altura líneas + banner no incluido
            # Mover arriba y limpiar desde cursor
            try:
                sys.stdout.write(f"\x1b[{altura}A")
                sys.stdout.write("\x1b[J")
                out = _pinta(idx)
                sys.stdout.write(out + "\n")
                sys.stdout.flush()
                altura = out.count("\n") + 1
            except Exception:  # noqa: BLE001
                pass
    except KeyboardInterrupt:
        return None
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:  # noqa: BLE001
            pass
        try:
            sys.stdout.write("\x1b[?25h")
            sys.stdout.write("\n")
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            pass


def checklist(titulo_txt: str, items: list, marcados=None, pie: str = None) -> list | None:
    """Checklist multi-selección estilo Debian: [*]/[ ] con Tab/Espacio/Enter.

    Gate idéntico a elegir_interactivo → None si sin tty (fallback textual).
    Con tty: ↑/↓ mueve foco, Espacio/Tab toggle, a todos, n ninguno, Enter confirma, ESC/q vacía.
    Retorna lista de items seleccionados (puede ser []) o None para fallback.
    """
    if os.environ.get("NO_COLOR") is not None:
        return None
    if os.environ.get("TERM", "") == "dumb":
        return None
    try:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            return None
    except Exception:  # noqa: BLE001
        return None
    try:
        import select
        import termios
        import tty
    except Exception:  # noqa: BLE001
        return None
    n = len(items)
    if n == 0:
        return []
    # Estado: set de índices marcados
    marcados_set = set()
    if marcados:
        for m in marcados:
            if m in items:
                marcados_set.add(items.index(m))
            elif isinstance(m, int) and 0 <= m < n:
                marcados_set.add(m)
    idx = 0
    # Paginación dinámica: máx 20, ajustado al alto de la terminal
    import shutil
    try:
        rows = shutil.get_terminal_size().lines
    except Exception:  # noqa: BLE001
        rows = 24
    overhead = 6  # borde+titulo+pie+base+separador
    page_size = min(20, max(5, rows - overhead - 2))
    page_size = min(page_size, n) if n else 5
    offset = 0
    try:
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
    except Exception:  # noqa: BLE001
        return None
    try:
        sys.stdout.write("\x1b[?25l")
        sys.stdout.flush()
    except Exception:  # noqa: BLE001
        pass

    def _line(i: int, texto: str, focused: bool) -> str:
        box = "[*]" if i in marcados_set else "[ ]"
        raw = f"{box} {texto}"
        if focused:
            return c(f" {raw} ", _NEGRITA, _BLANCO, _FONDO_AZUL)
        # No foco: caja gris, texto blanco negrita para el nombre
        if i in marcados_set:
            return f" {c(box, _NEGRITA, _BLANCO)} {texto_menu(texto)}"
        return f" {c(box, _GRIS)} {texto_menu(texto)}"

    def _pinta(sel: int):
        # Ventana visible
        nonlocal offset
        # Ajustar offset para que sel sea visible (flecha abajo scrollea)
        if sel < offset:
            offset = sel
        elif sel >= offset + page_size:
            offset = sel - page_size + 1
        visible = items[offset:offset + page_size]
        lineas = []
        for j, it in enumerate(visible):
            i = offset + j
            lineas.append(_line(i, it, i == sel))
        # Pie con paginación si hace falta
        cur_pie = pie
        if cur_pie is None:
            if n > page_size:
                cur_page = offset // page_size + 1
                tot_pages = (n + page_size - 1) // page_size
                cur_pie = f"↑/↓ mueve · Espacio marca · a todos/n ninguno · Enter confirma · ESC sale · Pág {cur_page}/{tot_pages} ({offset+1}-{min(offset+page_size,n)}/{n})"
            else:
                cur_pie = "↑/↓ mueve · Espacio marca · a todos/n ninguno · Enter confirma · ESC sale"
        return marco(titulo_txt, lineas, pie=cur_pie)

    altura = 0
    try:
        tty.setcbreak(fd)
        out = _pinta(idx)
        sys.stdout.write(out + "\n")
        sys.stdout.flush()
        altura = out.count("\n") + 1
        while True:
            r, _, _ = select.select([sys.stdin], [], [], 0.2)
            if not r:
                continue
            ch = os.read(fd, 3)
            if not ch:
                continue
            if ch in (b"\x1b[A", b"\x1bOA"):  # arriba
                idx = (idx - 1) % n
            elif ch in (b"\x1b[B", b"\x1bOB", b"\t", b"\x09"):  # abajo o Tab
                idx = (idx + 1) % n
            elif ch in (b" ", b"\x20"):  # Espacio toggle
                if idx in marcados_set:
                    marcados_set.remove(idx)
                else:
                    marcados_set.add(idx)
            elif ch in (b"a", b"A"):
                marcados_set = set(range(n))
            elif ch in (b"n", b"N"):
                marcados_set.clear()
            elif ch in (b"\r", b"\n"):
                return [items[i] for i in sorted(marcados_set)]
            elif ch == b"\x1b":  # ESC
                return []
            elif ch in (b"q", b"Q"):
                return []
            else:
                continue
            try:
                sys.stdout.write(f"\x1b[{altura}A")
                sys.stdout.write("\x1b[J")
                out = _pinta(idx)
                sys.stdout.write(out + "\n")
                sys.stdout.flush()
                altura = out.count("\n") + 1
            except Exception:  # noqa: BLE001
                pass
    except KeyboardInterrupt:
        return []
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:  # noqa: BLE001
            pass
        try:
            sys.stdout.write("\x1b[?25h\n")
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            pass


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
