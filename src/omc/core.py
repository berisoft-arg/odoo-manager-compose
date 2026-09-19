"""Núcleo compartido: rutas de datos, render, versiones, catálogos, puertos, reparto.

Resolución de datos (orden):
  1. $OMC_HOME/<nombre> ($ODOO_CREATOR_HOME como fallback legacy)
  2. ~/odoo-manager-compose/<nombre> (~/odoo-create/<nombre> como fallback legacy)
  3. /opt/omc/<nombre> (default en instalaciones nuevas)
  4. datos empaquetados (templates/, versions/ via importlib.resources)

Proyectos (orden en projects_home()):
  1. $OMC_PROJECTS
  2. $OMC_HOME ($ODOO_CREATOR_HOME legacy; compat: antes significaba proyectos)
  3. ~/odoo-manager-compose (si existe: migración de instalaciones previas)
  4. ~/odoo-create (si existe: migración legacy)
  5. /opt (default en instalaciones nuevas: /opt/<proyecto>)
"""
import json
import os
import re
import subprocess
from pathlib import Path

_NUEVO_HOME = "odoo-manager-compose"
_VIEJO_HOME = "odoo-create"
_OPT_DATA = Path("/opt/omc")
_OPT_PROJECTS = Path("/opt")


def _home_env() -> str:
    """Dir base via entorno: $OMC_HOME, fallback $ODOO_CREATOR_HOME."""
    return os.environ.get("OMC_HOME", "") or os.environ.get("ODOO_CREATOR_HOME", "")


def _projects_env() -> str:
    """Raíz de proyectos via entorno: $OMC_PROJECTS."""
    return os.environ.get("OMC_PROJECTS", "")


def _default_home() -> Path:
    """Home por defecto: nuevo si existe, viejo si existe (migración), nuevo si ninguno."""
    nuevo = Path.home() / _NUEVO_HOME
    viejo = Path.home() / _VIEJO_HOME
    if nuevo.is_dir():
        return nuevo
    if viejo.is_dir():
        return viejo
    return nuevo


def _home_candidates(nombre: str):
    cands = []
    env = _home_env()
    if env:
        cands.append(Path(env) / nombre)
    cands.append(Path.home() / _NUEVO_HOME / nombre)
    cands.append(Path.home() / _VIEJO_HOME / nombre)
    cands.append(_OPT_DATA / nombre)
    return cands


def data_path(nombre: str) -> Path | None:
    """Ruta editable de un dato de usuario (catálogos, ejemplo bundle)."""
    for p in _home_candidates(nombre):
        if p.exists():
            return p
    return None


ENTORNOS = ["desarrollo", "produccion"]


def data_home() -> Path:
    """Dir de datos de usuario (catálogos editables, estado del monitor).

    $OMC_HOME, si no legados existentes (migración), si no /opt/omc.
    """
    env = _home_env()
    if env:
        return Path(env)
    base = _default_home()
    if base.is_dir():
        return base
    return _OPT_DATA


def data_path_write(nombre: str) -> Path:
    """Ruta donde escribir un dato de usuario (crea el dir si hace falta)."""
    base = data_home()
    asegurar_escribible(base, "datos")
    base.mkdir(parents=True, exist_ok=True)
    return base / nombre


def projects_home() -> Path:
    """Raíz donde viven los proyectos generados (/opt/<proyecto> por default).

    $OMC_PROJECTS, si no $OMC_HOME (compat: antes significaba proyectos),
    si no legados existentes (migración), si no /opt.
    """
    proj = _projects_env()
    if proj:
        return Path(proj)
    env = _home_env()
    if env:
        return Path(env)
    base = _default_home()
    if base.is_dir():
        return base
    return _OPT_PROJECTS


def asegurar_escribible(ruta: Path, rol: str) -> None:
    """Sale con instrucción de sudo único si no se puede escribir.

    `rol`: "proyectos" o "datos", para el mensaje.
    """
    import sys as _sys
    p = Path(ruta)
    base = p if p.is_dir() else p.parent
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    if base.is_dir() and os.access(base, os.W_OK):
        return
    _sys.exit(
        f"{base} no es escribible ({rol}). Una vez en el host:\n"
        f"  sudo mkdir -p {base} && sudo chown $(id -u):$(id -g) {base}\n"
        f"Después no se necesita sudo. Alternativa sin sudo: "
        f"OMC_PROJECTS=~/omc-proyectos OMC_HOME=~/omc-data omc"
    )


def default_salida(nombre: str, explicit=None) -> Path:
    """Carpeta destino de un proyecto nuevo: --salida, si no <proyectos>/<nombre>."""
    if explicit:
        return Path(explicit).resolve()
    return (projects_home() / nombre).resolve()


def find_proyecto(explicit=None) -> Path:
    """Resuelve proyecto: explícito, cwd con addons/, o sys.exit guiado (igual que antes)."""
    import sys as _sys
    if explicit:
        p = Path(explicit).resolve()
        if not (p / "addons").is_dir():
            _sys.exit(f"{p} no parece un proyecto (sin ./addons).")
        return p
    cwd = Path.cwd()
    if (cwd / "addons").is_dir():
        return cwd
    try:
        hijos = sorted(d.name for d in cwd.iterdir()
                       if d.is_dir() and (d / "addons").is_dir())
    except OSError:
        hijos = []
    if (cwd / "src" / "omc").is_dir() or hijos:
        msg = "No estás dentro de un proyecto (estás en el dir maestro)."
        if hijos:
            msg += f" Proyectos: {', '.join(hijos)}. Entra a uno: cd {hijos[0]}"
        _sys.exit(msg + " O usa --proyecto <ruta>.")
    _sys.exit("No estás en un proyecto (no veo ./addons). Usa --proyecto <ruta>.")


def data_text(nombre: str) -> str:
    """Contenido de un archivo de data/ empaquetado (ej addons-bundle.ejemplo.json)."""
    try:
        from importlib import resources
        return (resources.files("omc") / "data" / nombre).read_text(encoding="utf-8")
    except (ImportError, FileNotFoundError, TypeError):
        for p in _home_candidates(os.path.join("data", nombre)):
            if p.exists():
                return p.read_text(encoding="utf-8")
        for p in _home_candidates(nombre):
            if p.exists():
                return p.read_text(encoding="utf-8")
        raise FileNotFoundError(f"dato {nombre}")


def template_text(nombre: str) -> str:
    """Texto de plantilla empaquetada (templates/). Falla con FileNotFoundError si falta."""
    try:
        from importlib import resources
        return (resources.files("omc") / "templates" / nombre).read_text(encoding="utf-8")
    except (ImportError, FileNotFoundError, TypeError):
        for p in _home_candidates(os.path.join("templates", nombre)):
            if p.exists():
                return p.read_text(encoding="utf-8")
        raise FileNotFoundError(f"template {nombre}")


def version_files() -> list:
    """Rutas versions/*.env (paquete o repo clásico)."""
    try:
        from importlib import resources
        base = resources.files("omc") / "versions"
        if base.is_dir():
            return sorted(base.glob("*.env"))
    except (ImportError, TypeError):
        pass
    for p in _home_candidates("versions"):
        if p.is_dir():
            return sorted(p.glob("*.env"))
    return []


def _read_text(p) -> str:
    if isinstance(p, Path):
        return p.read_text(encoding="utf-8")
    with open(p, encoding="utf-8") as f:
        return f.read()


def cargar_versions(files=None) -> dict:
    """Lee versions/*.env -> {'18': {'odoo': ..., 'postgres': ..., 'version': ...}}."""
    versions = {}
    files = files if files is not None else version_files()
    if not files:
        raise FileNotFoundError("no hay versions/*.env")
    for f in sorted(files, key=lambda x: str(x)):
        data = {}
        for line in _read_text(f).splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
        ver = data.get("ODOO_VERSION", Path(str(f)).stem)
        versions[ver] = {
            "odoo": data.get("ODOO_IMAGE", f"odoo:{ver}"),
            "postgres": data.get("POSTGRES_IMAGE", "postgres:16"),
            "version": ver,
        }
    if not versions:
        raise FileNotFoundError("no hay versiones en versions/*.env")
    return versions


def _load_json_file(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def cargar_catalogo() -> dict:
    for p in _home_candidates("addons-catalog.json"):
        data = _load_json_file(p)
        if isinstance(data, dict):
            return data
    try:
        from importlib import resources
        data = json.loads((resources.files("omc") / "data" / "addons-catalog.json"
                           ).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:  # noqa: BLE001
        pass
    return {}


def cargar_localizaciones() -> dict:
    for p in _home_candidates("localizaciones.json"):
        data = _load_json_file(p)
        if isinstance(data, dict):
            return data
    try:
        from importlib import resources
        data = json.loads((resources.files("omc") / "data" / "localizaciones.json"
                           ).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:  # noqa: BLE001
        pass
    return {}


def render(texto: str, mapping: dict) -> str:
    for k, v in mapping.items():
        texto = texto.replace("{{" + k + "}}", str(v))
    return texto


def sin_renderizar(texto: str) -> list:
    """Placeholders {{X}} que quedaron sin sustituir."""
    return sorted(set(re.findall(r"\{\{([A-Za-z0-9_]+)\}\}", texto)))


def puerto_en_uso(puerto: int) -> bool:
    """True si el puerto está ocupado en el host o publicado por algún contenedor docker."""
    import socket
    s = socket.socket()
    s.settimeout(0.3)
    try:
        if s.connect_ex(("127.0.0.1", puerto)) == 0:
            return True
    finally:
        s.close()
    try:
        r = subprocess.run(["docker", "ps", "--format", "{{.Ports}}"],
                           text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=15)
        if r.returncode == 0:
            for m in re.finditer(r"0\.0\.0\.0:(\d+)->", r.stdout or ""):
                if int(m.group(1)) == puerto:
                    return True
    except Exception:  # noqa: BLE001
        pass
    return False


def puerto_libre(desde: int) -> int:
    """Primer puerto TCP libre desde 'desde' (evita choques entre proyectos)."""
    p = desde
    while p < desde + 100:
        if not puerto_en_uso(p):
            return p
        p += 1
    return desde


def parse_addon_spec(spec: str):
    """'oca/server-tools:auditlog,auto_backup' -> ('oca','server-tools',['auditlog','auto_backup'])"""
    org_repo, _, mods = spec.partition(":")
    mods_list = [m.strip() for m in mods.split(",") if m.strip()]
    if "/" in org_repo:
        org, repo = org_repo.split("/", 1)
    else:
        org, repo = "oca", org_repo
    return org.strip().lower(), repo.strip(), mods_list


def parse_seleccion(raw: str, opciones: list):
    """'1,5,auditlog' -> (validos, invalidos). Acepta números, nombres y 'todo'."""
    if raw.strip().lower() in ("todo", "todos", "all", "*"):
        return list(opciones), []
    validos, invalidos, vistos = [], [], set()
    for tok in [t.strip() for t in raw.replace(" ", ",").split(",") if t.strip()]:
        nombre = None
        if tok.isdigit() and 1 <= int(tok) <= len(opciones):
            nombre = opciones[int(tok) - 1]
        elif tok in opciones:
            nombre = tok
        if nombre and nombre not in vistos:
            validos.append(nombre)
            vistos.add(nombre)
        elif not nombre:
            invalidos.append(tok)
    return validos, invalidos


def odoo_to_branch(odoo_ver: str) -> str:
    return f"{odoo_ver}.0"


def leer_env(proyecto) -> dict:
    """Lee .env del proyecto a dict (sin ejecutar nada)."""
    from pathlib import Path as _P
    d = {}
    f = _P(proyecto) / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                d[k.strip()] = v.strip()
    return d


def read_env_branch(proyecto) -> str:
    from pathlib import Path as _P
    p = _P(proyecto)
    env = p / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("ODOO_VERSION="):
                return odoo_to_branch(line.split("=", 1)[1].strip())
    return ""


def load_catalog() -> dict:
    for p in _home_candidates("addons-catalog.json"):
        data = _load_json_file(p)
        if isinstance(data, dict):
            return data
    try:
        from importlib import resources
        data = json.loads((resources.files("omc") / "data" / "addons-catalog.json"
                           ).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:  # noqa: BLE001
        pass
    return {}


def fmt_mem(mb: float) -> str:
    """4608 -> 4.5GB, 1024 -> 1GB, 300 -> 300MB."""
    g = mb / 1024
    if abs(g - round(g, 1)) < 0.005 and g >= 1:
        g = round(g, 1)
        return f"{int(g) if g == int(g) else g}GB"
    return f"{int(round(mb))}MB"


def reparto_vps(vcpus: float, ram_gb: float, con_nginx: bool) -> dict:
    """Reparte vCPU/RAM del VPS: sistema + nginx fijos, odoo ~70/62%, db resto.

    Tuning Postgres: shared_buffers 20% del total, effective_cache 50%.
    shared_buffers además se topa al 60% del límite del contenedor db
    (en VPS chicos el 20% del total excedería el cgroup y OOMea).
    Workers Odoo: 2CPU+1.
    """
    cpu = max(vcpus - 0.5, 0.5)
    mem = max(ram_gb - 0.5, 1.0)
    ng_c, ng_m = (0.25, 0.25) if con_nginx else (0.0, 0.0)
    odoo_cpus = round(max((cpu - ng_c) * 0.70, 0.25), 2)
    db_cpus = round(max((cpu - ng_c) * 0.30, 0.25), 2)
    odoo_mem = round(max((mem - ng_m) * 0.62, 0.5), 1)
    db_mem = round(max((mem - ng_m) * 0.30, 0.5), 1)
    total_mb = ram_gb * 1024
    db_mb = db_mem * 1024
    workers_n = min(int(2 * vcpus + 1), 16)
    # Límites de memoria por worker (bytes): la RAM de odoo repartida en partes
    # iguales; soft recicla con gracia, hard mata (1.5x). Piso 256MB para VPS chicos.
    _soft = max(int(odoo_mem * 1024**3) // workers_n, 256 * 1024**2)
    return {
        "ODOO_CPUS": str(odoo_cpus), "ODOO_MEM": fmt_mem(odoo_mem * 1024),
        "ODOO_CPUS_RES": str(round(odoo_cpus / 2, 2)), "ODOO_MEM_RES": fmt_mem(round(odoo_mem / 2, 1) * 1024),
        "DB_CPUS": str(db_cpus), "DB_MEM": fmt_mem(db_mem * 1024),
        "DB_CPUS_RES": str(round(db_cpus / 2, 2)), "DB_MEM_RES": fmt_mem(round(db_mem / 2, 1) * 1024),
        "PG_SHARED_BUFFERS": fmt_mem(min(total_mb * 0.20, db_mb * 0.60, 8192)),
        "PG_EFFECTIVE_CACHE": fmt_mem(min(total_mb * 0.50, 16384)),
        "PG_WORK_MEM": fmt_mem(max(total_mb * 0.20 / 100, 4)),
        "PG_MAINT_MEM": fmt_mem(min(max(total_mb * 0.05, 64), 1024)),
        "PG_MAX_CONN": "100",
        "ODOO_WORKERS": str(workers_n),
        "ODOO_LIMIT_SOFT": str(_soft),
        "ODOO_LIMIT_HARD": str(int(_soft * 1.5)),
    }


def bloque_deploy(cpus_lim: str, mem_lim: str, cpus_res: str, mem_res: str) -> str:
    return (f"    deploy:\n      resources:\n"
            f"        limits: {{cpus: '{cpus_lim}', memory: {mem_lim}}}\n"
            f"        reservations: {{cpus: '{cpus_res}', memory: {mem_res}}}\n")


class Project:
    """Proyecto desplegado: acceso tipado a .env/repos.json/conf + guardado atómico."""

    def __init__(self, ruta):
        self.ruta = Path(ruta).resolve()
        if not (self.ruta / "docker-compose.yml").exists():
            raise ValueError(f"{self.ruta} no parece un proyecto (sin docker-compose.yml)")

    def env(self) -> dict:
        d = {}
        f = self.ruta / ".env"
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s and not s.startswith("#") and "=" in s:
                    k, v = s.split("=", 1)
                    d[k.strip()] = v.strip()
        return d

    def repos(self) -> list:
        f = self.ruta / "addons" / "repos.json"
        if not f.exists():
            return []
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except ValueError:
            return []

    def guardar_repos(self, repos: list) -> None:
        """Escritura atómica (tmp + rename) para no corromper ante cortes."""
        f = self.ruta / "addons" / "repos.json"
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(repos, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(f)

    def odoo_conf_texto(self) -> str:
        return (self.ruta / "config" / "odoo.conf").read_text(encoding="utf-8")

    def guardar_odoo_conf(self, texto: str) -> None:
        f = self.ruta / "config" / "odoo.conf"
        tmp = f.with_suffix(".conf.tmp")
        tmp.write_text(texto, encoding="utf-8")
        tmp.replace(f)
