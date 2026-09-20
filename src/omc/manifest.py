"""Manifests, índice de módulos en disco y análisis de dependencias."""
import re
import subprocess
from pathlib import Path

from .core import Project
from .github import modulos_nativos

CORE_SIEMPRE = {
    # Nativos Odoo CE bien conocidos (vale aunque el contenedor esté apagado)
    "base", "web", "mail", "contacts", "calendar", "crm", "portal",
    "account", "account_payment", "account_debit_note", "account_bank_statement",
    "sale", "sale_management", "sale_stock", "purchase", "purchase_stock",
    "stock", "stock_account", "mrp", "pos", "point_of_sale", "project",
    "hr", "hr_holidays", "hr_expense", "hr_attendance", "website",
    "delivery", "auth_signup", "l10n_ar", "l10n_latam_base", "l10n_latam_invoice_document",
}

ALIASES_PIP = {"openssl": "pyOpenSSL"}


def load_repos(proyecto) -> list:
    p = proyecto if isinstance(proyecto, Path) else Path(proyecto)
    return Project(p).repos() if (p / "docker-compose.yml").exists() else _load_repos_raw(p)


def _load_repos_raw(p: Path) -> list:
    f = p / "addons" / "repos.json"
    if not f.exists():
        return []
    import json
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except ValueError:
        return []


def save_repos(proyecto, repos: list) -> None:
    import json
    p = proyecto if isinstance(proyecto, Path) else Path(proyecto)
    f = p / "addons" / "repos.json"
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(repos, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(f)


def anotar_sha(entry: dict, dest) -> None:
    """Fija el SHA descargado en la entrada de repos.json (reproducibilidad)."""
    from .gitutils import git_sha
    dest = dest if isinstance(dest, Path) else Path(dest)
    if dest.is_dir():
        sha = git_sha(dest)
        if sha:
            entry["sha"] = sha


def leer_manifest(mod_dir: Path):
    """Lee __manifest__.py y devuelve dict (o {})."""
    import ast
    for name in ("__manifest__.py", "__openerp__.py"):
        f = Path(mod_dir) / name
        if f.exists():
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
                data = ast.literal_eval(tree.body[0].value)
                return data if isinstance(data, dict) else {}
            except Exception:  # noqa: BLE001
                return {}
    return {}


def normalizar_req(linea: str) -> str:
    """Corrige nombres PyPI conocidos (OpenSSL->pyOpenSSL). URLs y flags intactos."""
    s = linea.strip()
    if not s or s.startswith(("#", "-", "git+", "http://", "https://", ".")):
        return s
    m = re.match(r"^([A-Za-z0-9_.-]+)(.*)$", s)
    if not m:
        return s
    nombre, resto = m.group(1), m.group(2)
    return ALIASES_PIP.get(nombre.lower(), nombre) + resto


def quitar_m2crypto(reqs: list) -> tuple:
    """M2Crypto fuera del pip: no compila en imágenes slim y choca con el
    python3-m2crypto de apt (lo que usa la localización AR).

    Devuelve (lista_filtrada, sacadas)."""
    def _base(l):
        return re.split(r"[=<>;\s\[]", l.strip(), 1)[0].strip().lower()
    sacadas = [l for l in reqs if _base(l) == "m2crypto"]
    return [l for l in reqs if _base(l) != "m2crypto"], sacadas


def _num(ver: str) -> tuple:
    """Tupla comparable de la parte numérica ('1.8.22' -> (1, 8, 22))."""
    partes = []
    for tok in re.split(r"[.]", ver.strip().split("+")[0].split("-")[0]):
        m = re.match(r"(\d+)", tok)
        partes.append(int(m.group(1)) if m else 0)
    return tuple(partes) or (0,)


def detectar_conflictos(reqs: list) -> list:
    """Pins incompatibles del mismo paquete (solo stdlib, sin pip).

    Agrupa por nombre base y compara especificadores (==, !=, >=, <=, >, <, ~=).
    Devuelve descripciones humanas; vacío si no hay choque probable. No falla
    ante líneas git/URL/flags: esas se ignoran.
    """
    from collections import defaultdict
    grupos = defaultdict(list)
    for l in reqs:
        s = l.strip()
        if (not s or s.startswith(("#", "-", "."))
                or s.startswith(("git+", "http://", "https://"))):
            continue
        m = re.match(r"^([A-Za-z0-9_.-]+)\s*(.*)$", s)
        if not m:
            continue
        nombre, resto = m.group(1).lower(), m.group(2).strip()
        resto = resto.split(";")[0].strip()  # markers fuera
        if not resto:
            continue
        grupos[nombre].append((s, resto))
    hallados = []
    for nombre, pares in grupos.items():
        if len(pares) < 2:
            continue
        fijos = []
        for original, spec in pares:
            for parte in spec.split(","):
                parte = parte.strip()
                m = re.match(r"^(==|!=|>=|<=|>|<|~=|===)\s*([^\s,;]+)", parte)
                if m:
                    fijos.append((m.group(1), m.group(2), original))
        vistos = set()
        for i, (op1, v1, o1) in enumerate(fijos):
            for op2, v2, o2 in fijos[i + 1:]:
                n1, n2 = _num(v1), _num(v2)
                choca = False
                if op1 == "==" and op2 == "==" and n1 != n2:
                    choca = True
                elif {op1, op2} == {"==", "!="} and n1 == n2:
                    choca = True
                elif op1 == "==" and op2 in (">=", ">", "~=") and not _cumple(n1, op2, n2):
                    choca = True
                elif op2 == "==" and op1 in (">=", ">", "~=") and not _cumple(n2, op1, n1):
                    choca = True
                elif op1 == "==" and op2 in ("<=", "<") and not _cumple(n1, op2, n2):
                    choca = True
                elif op2 == "==" and op1 in ("<=", "<") and not _cumple(n2, op1, n1):
                    choca = True
                if choca:
                    clave = tuple(sorted((o1, o2)))
                    if clave not in vistos:
                        vistos.add(clave)
                        hallados.append(f"{nombre}: '{o1}' vs '{o2}'")
    return hallados


def _cumple(ver: tuple, op: str, ref: tuple) -> bool:
    """True si la versión fija ver satisface op ref (con ~= como compatible)."""
    if op in (">=", "==="):
        return ver >= ref
    if op == ">":
        return ver > ref
    if op == "<=":
        return ver <= ref
    if op == "<":
        return ver < ref
    if op == "~=":
        n = len(ref)
        if n <= 1:
            return ver >= ref
        return ver[:n - 1] == ref[:n - 1] and ver >= ref
    return True


def iterar_modulos(base: Path):
    """Rinde (nombre, path) de módulos: manifest directo o un nivel adentro.

    Cubre repos multi-módulo bajo custom/ (ej custom/odoo-argentina/l10n_ar_ledger).
    """
    try:
        subs = [m for m in base.iterdir() if m.is_dir() and not m.name.startswith(".")]
    except OSError:
        return
    for m in subs:
        if (m / "__manifest__.py").exists() or (m / "__openerp__.py").exists():
            yield m.name, m
        else:
            try:
                for n in m.iterdir():
                    if n.is_dir() and ((n / "__manifest__.py").exists() or
                                       (n / "__openerp__.py").exists()):
                        yield n.name, n
            except OSError:
                pass


def indice_modulos_disco(proyecto: Path):
    """Mapa módulo -> {'path': Path, 'instalado': bool}.

    Instalado = en repos.json/custom/single (lo que Odoo ve).
    No instalado pero disponible = subdir con manifest dentro de un repo clonado.
    """
    p = proyecto if isinstance(proyecto, Path) else Path(proyecto)
    idx = {}
    for r in load_repos(p):
        base = p / r.get("path", "")
        if not base.is_dir():
            continue
        instalados = set(r.get("modules", []))
        # Módulos del repo: vía git ls-tree (el sparse oculta lo no descargado del disco).
        # Solo nombres de árbol: no baja blobs.
        candidatos = set()
        try:
            lr = subprocess.run(["git", "-C", str(base), "ls-tree", "-r", "--name-only", "HEAD"],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=120)
            if lr.returncode == 0:
                for line in (lr.stdout or "").splitlines():
                    if "/" in line and line.rsplit("/", 1)[-1] in ("__manifest__.py", "__openerp__.py"):
                        candidatos.add(line.split("/")[0])
        except Exception:  # noqa: BLE001
            pass
        if not candidatos:
            # no es git o falló: barrido de disco
            try:
                for m in base.iterdir():
                    if m.is_dir() and (m / "__manifest__.py").exists():
                        candidatos.add(m.name)
            except OSError:
                pass
        for name in candidatos:
            idx.setdefault(name, {"path": base / name, "instalado": name in instalados,
                                  "repo_path": r.get("path", "")})
    for _d, _tag in ((p / "addons" / "custom", "addons/custom"),
                     (p / "addons" / "extras", "addons/extras")):
        if _d.is_dir():
            for name, path in iterar_modulos(_d):
                idx.setdefault(name, {"path": path, "instalado": True, "repo_path": _tag})
    return idx


def modulos_base_odoo(proyecto: Path):
    """(set core, conocido). Leído del contenedor odoo; si está apagado, vacío + False."""
    try:
        r = subprocess.run(["docker", "compose", "exec", "-T", "odoo", "sh", "-c",
                            "ls -d /usr/lib/python3*/dist-packages/odoo/addons/*/ 2>/dev/null || "
                            "ls -d /usr/local/lib/python3*/dist-packages/odoo/addons/*/ 2>/dev/null"],
                           cwd=str(proyecto), text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=30)
        mods = set()
        for line in (r.stdout or "").splitlines():
            name = line.rstrip("/").split("/")[-1]
            if name and not name.startswith("."):
                mods.add(name)
        return mods, r.returncode == 0
    except Exception:  # noqa: BLE001
        return set(), False


def base_total(proyecto: Path):
    """Unión: contenedor + lista estática + GitHub por rama. Devuelve (set, confirmado)."""
    from .core import Project as _P
    p = proyecto if isinstance(proyecto, Path) else Path(proyecto)
    cont, ok = modulos_base_odoo(p)
    ver = ""
    try:
        ver = _P(p).env().get("ODOO_VERSION", "") if (p / "docker-compose.yml").exists() else ""
    except ValueError:
        pass
    nat = modulos_nativos(ver) or set()
    return set(cont) | CORE_SIEMPRE | nat, ok


def analizar_depends(proyecto: Path):
    """Devuelve (reporte, faltantes_mismo_repo, faltantes_total).

    faltantes_mismo_repo: {repo_path: set(mods)} descargables con sparse-checkout add.
    """
    from .core import Project as _P
    p = proyecto if isinstance(proyecto, Path) else Path(proyecto)
    idx = indice_modulos_disco(p)
    cont, cont_ok = modulos_base_odoo(p)
    ver = ""
    try:
        ver = _P(p).env().get("ODOO_VERSION", "") if (p / "docker-compose.yml").exists() else ""
    except ValueError:
        pass
    # Autoridad: árbol github.com/odoo/odoo/tree/<ver>/addons + contenedor + lista estática.
    # Si no está en ninguno, NO es nativo.
    nativos = modulos_nativos(ver)
    base = set(nativos) if nativos is not None else set()
    base |= set(cont) | CORE_SIEMPRE
    if nativos is None and not cont_ok:
        print("  (sin red ni contenedor: lo desconocido se marca base? sin confirmar)")
    reporte, mismo_repo, total = {}, {}, set()
    instalados = sorted(n for n, v in idx.items() if v["instalado"])
    for mod in instalados:
        man = leer_manifest(idx[mod]["path"])
        for dep in man.get("depends", []) or []:
            if dep in idx and idx[dep]["instalado"]:
                estado = "ok"
            elif dep in idx:
                estado = "mismo-repo"
                mismo_repo.setdefault(idx[dep]["repo_path"], set()).add(dep)
            elif dep in base:
                estado = "base"
            elif nativos is None and not cont_ok:
                estado = "base?"
            else:
                estado = "falta"
                total.add(dep)
            reporte.setdefault(mod, []).append((dep, estado))
    return reporte, mismo_repo, total
