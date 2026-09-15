"""GitHub: config local, API con caché, búsqueda de módulos, nativos Odoo."""
import json
import os
import re
from pathlib import Path


def gh_config_path() -> Path:
    """config.json: ~/.config/omc (legacy ~/.config/odoo-create si existe y el nuevo no)."""
    nuevo = Path.home() / ".config" / "omc" / "config.json"
    viejo = Path.home() / ".config" / "odoo-create" / "config.json"
    if nuevo.exists() or not viejo.exists():
        return nuevo
    return viejo


def gh_config_leer() -> dict:
    try:
        p = gh_config_path()
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return {}


def gh_config_guardar(cfg: dict) -> Path:
    p = gh_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return p


def gh_token() -> str:
    return os.environ.get("GITHUB_TOKEN", "") or os.environ.get("GIT_TOKEN", "") or \
        gh_config_leer().get("github_token", "")


def gh_org() -> str:
    return os.environ.get("GITHUB_ORG", "") or os.environ.get("GITHUB_USER", "") or \
        gh_config_leer().get("github_org", "")


def gh_api_get(path: str):
    """GET a api.github.com (con token si hay). Devuelve objeto o None."""
    import urllib.request as _url
    req = _url.Request("https://api.github.com" + path,
                       headers={"Accept": "application/vnd.github+json",
                                "User-Agent": "omc"})
    token = gh_token()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with _url.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return None


def gh_validar_token(token: str) -> str | None:
    """Devuelve login si el token es válido, None si no."""
    import urllib.request as _url
    req = _url.Request("https://api.github.com/user",
                       headers={"Accept": "application/vnd.github+json",
                                "User-Agent": "omc",
                                "Authorization": f"Bearer {token}"})
    try:
        with _url.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode()).get("login")
    except Exception:  # noqa: BLE001
        return None


def cache_dir() -> Path:
    d = Path.home() / ".cache" / "omc" / "repo-index"
    d.mkdir(parents=True, exist_ok=True)
    return d


def repo_topdirs_api(url: str, branch: str):
    """Top-dirs de un repo GitHub vía API (1 llamada, con caché en disco). None si no aplica."""
    key = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{url}__{branch}") + ".json"
    cf = cache_dir() / key
    try:
        if cf.exists():
            return json.loads(cf.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    owner, repo = "", ""
    if "github.com" in url:
        try:
            parts = url.split("github.com/")[-1].strip("/").removesuffix(".git").split("/")
            owner, repo = parts[0], parts[1]
        except IndexError:
            return None
    else:
        return None
    data = gh_api_get(f"/repos/{owner}/{repo}/contents?ref={branch}")
    if not isinstance(data, list):
        return None
    skip = {".github", ".oca", "setup", "docs", "migrations"}
    dirs = sorted(e["name"] for e in data
                  if isinstance(e, dict) and e.get("type") == "dir"
                  and e.get("name") and not e["name"].startswith(".")
                  and e["name"] not in skip)
    try:
        cf.write_text(json.dumps(dirs), encoding="utf-8")
    except OSError:
        pass
    return dirs


def repos_de_org(org: str):
    """[(owner, repo, url)] de una org/usuario GitHub (caché 1 día). Incluye privados con token."""
    import time as _t
    org = (org or "").strip()
    if not org:
        return []
    key = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"org__{org}") + ".json"
    cf = cache_dir() / key
    ahora = int(_t.time())
    try:
        if cf.exists():
            data = json.loads(cf.read_text(encoding="utf-8"))
            if ahora - data.get("ts", 0) < 86400:
                return data.get("repos", [])
    except (OSError, ValueError):
        pass
    repos = []
    for endpoint in (f"/orgs/{org}/repos?per_page=100", f"/users/{org}/repos?per_page=100"):
        data = gh_api_get(endpoint)
        if isinstance(data, list) and data:
            for e in data:
                if isinstance(e, dict) and e.get("name") and not e.get("archived"):
                    own = e.get("owner", {}).get("login", org)
                    repos.append((own, e["name"], f"https://github.com/{own}/{e['name']}"))
            break
    try:
        cf.write_text(json.dumps({"ts": ahora, "repos": repos}), encoding="utf-8")
    except OSError:
        pass
    return repos


SUBDIRS_PROPIOS = {"oca", "adhoc", "cybrosys", "mates", "codize"}

KNOWN_ORGS = {
    "oca": "OCA",
    "adhoc": "ingadhoc",
    "ingadhoc": "ingadhoc",
    "cybrosys": "CybroOdoo",
    "codize": "codize-app",
    "cybroodoo": "CybroOdoo",
    "mates": "odoomates",
    "odoomates": "odoomates",
}

INV_ORGS = {"oca": "oca", "ingadhoc": "adhoc",
            "cybroodoo": "cybrosys", "odoomates": "mates",
            "codize-app": "codize", "codize": "codize"}


def git_auth_args(url: str):
    """Args extra para git con repos privados GitHub sin guardar el token.

    El token NUNCA se guarda en repos.json ni en el remote.
    """
    token = gh_token()
    if token and url.startswith("https://github.com"):
        import base64
        b64 = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        return ["-c", f"http.extraHeader=AUTHORIZATION: basic {b64}"]
    return []


def es_url(s: str) -> bool:
    s = s.strip()
    return s.startswith(("http://", "https://", "git@", "ssh://")) or "://" in s


def repo_desde_url(url: str) -> str:
    return url.rstrip("/").split("/")[-1].removesuffix(".git").split(":")[-1]


def dueno_de_url(url: str) -> str:
    """Dueño sanitizado de una URL git (para carpeta propia). '' si no se deduce."""
    u = (url or "").strip()
    own = ""
    if "://" in u:
        from urllib.parse import urlparse
        parts = urlparse(u).path.strip("/").split("/")
        own = parts[0] if parts else ""
    elif ":" in u:
        own = u.split(":")[-1].split("/")[0]
    return re.sub(r"[^A-Za-z0-9_-]+", "", own).lower()


def org_subdir(org: str, url: str = "") -> str:
    """Carpeta bajo addons/. Conocidos -> fija; resto -> dueño de la URL.

    custom/ queda SOLO para módulos propios a mano (nunca se clona ahí).
    """
    o = (org or "").lower()
    if o == "oca":
        return "oca"
    if o in ("adhoc", "ingadhoc"):
        return "adhoc"
    if o in ("cybrosys", "cybroodoo"):
        return "cybrosys"
    if o in ("codize", "codize-app"):
        return "codize"
    if o in ("mates", "odoomates"):
        return "mates"
    if o in SUBDIRS_PROPIOS:
        return o
    return dueno_de_url(url) or "custom"


def org_desde_url(url: str) -> str:
    u = url.strip().lower()
    if "://" in u:
        from urllib.parse import urlparse
        parts = urlparse(u).path.strip("/").split("/")
        owner = parts[0] if parts else ""
    elif ":" in u:
        owner = u.split(":")[-1].split("/")[0]
    else:
        owner = ""
    owner = re.sub(r"[^A-Za-z0-9_-]+", "", owner)
    if not owner:
        return "custom"
    return INV_ORGS.get(owner, owner)


def resolve_repo(org: str, repo: str, url: str, catalog: dict):
    """Devuelve (org, repo, url). Acepta 'OCA/server-tools', URL pegada o repo corto + --org/--url.

    El --org manda: se busca primero en esa sección (hay nombres repetidos,
    ej account-financial-tools existe en OCA y en AdHoc).
    """
    if url:
        return org, repo, url
    if es_url(repo):
        # URL pegada directo (ej https://github.com/ingadhoc/account-financial-tools):
        # org según el dueño; desconocido -> custom (salvo --org explícito no-default)
        u = repo.strip()
        owner = ""
        if "://" in u:
            from urllib.parse import urlparse
            parts = urlparse(u).path.strip("/").split("/")
            owner = parts[0].lower() if parts else ""
        elif ":" in u:
            owner = u.split(":")[-1].split("/")[0].lower()
        inv = {"oca": "oca", "ingadhoc": "adhoc",
               "cybroodoo": "cybrosys", "odoomates": "mates",
               "codize-app": "codize", "codize": "codize"}
        if owner in inv:
            org = inv[owner]
        elif org == "oca":
            org = "custom"
        return org, repo_desde_url(u), u
    if "/" in repo:
        o, r = repo.split("/", 1)
        return o, r, f"https://github.com/{o}/{r}"
    for key in (org, org.lower(), org.upper()):
        for entry in catalog.get(key, []):
            if isinstance(entry, dict) and entry.get("repo") == repo:
                return org, repo, entry["url"]
    for section, entries in catalog.items():
        if section in (org, org.lower(), org.upper()) or not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and entry.get("repo") == repo:
                print(f"  Aviso: '{repo}' no está en [{org}], uso [{section}]: {entry['url']}")
                return section, repo, entry["url"]
    base = KNOWN_ORGS.get(org.lower(), org)
    return org, repo, f"https://github.com/{base}/{repo}"


def buscar_modulo(mod: str, branch: str, catalog: dict, progreso: bool = False):
    """[(org, repo, url)] del catálogo (+ tu org) con el módulo en esa rama.

    Búsqueda en paralelo con caché en disco.
    """
    from concurrent.futures import ThreadPoolExecutor
    entradas = []
    for section, entries in catalog.items():
        if not isinstance(entries, list):
            continue
        for e in entries:
            if isinstance(e, dict) and e.get("repo") and e.get("url"):
                entradas.append((section, e["repo"], e["url"]))
    for o, r, u in repos_de_org(gh_org()):
        entradas.append((f"@{o}", r, u))
    unicas, vistos = [], set()
    for section, repo, url in entradas:
        if (url, branch) not in vistos:
            vistos.add((url, branch))
            unicas.append((section, repo, url))
    if progreso:
        print(f"  Buscando {mod} en {len(unicas)} repos del catálogo...", flush=True)

    def _check(item):
        section, repo, url = item
        try:
            dirs = repo_topdirs_api(url, branch)
        except Exception:  # noqa: BLE001
            return None
        return (section, repo, url) if dirs and mod in dirs else None

    hits = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for res in ex.map(_check, unicas):
            if res:
                hits.append(res)
    orden = {"oca": 0, "adhoc": 1, "mates": 2, "cybrosys": 3, "codize": 4, "custom": 5}
    return sorted(hits, key=lambda x: (0 if x[0].startswith("@") else 1, orden.get(x[0], 9)))


def modulos_nativos(odoo_ver: str):
    """Set de nativos desde github.com/odoo/odoo/tree/<ver>/addons (caché 30 días).

    None si sin red y sin caché (no se puede afirmar nada).
    """
    ver = (odoo_ver or "").strip()
    if not ver:
        return None
    branch = ver if "." in ver else f"{ver}.0"
    key = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"odoo-core__{branch}") + ".json"
    cf = cache_dir() / key
    import time as _t
    ahora = int(_t.time())
    viejo = None
    try:
        if cf.exists():
            data = json.loads(cf.read_text(encoding="utf-8"))
            if ahora - data.get("ts", 0) < 30 * 86400:
                return set(data.get("mods", []))
            viejo = set(data.get("mods", []))
    except (OSError, ValueError):
        viejo = None
    data = gh_api_get(f"/repos/odoo/odoo/contents/addons?ref={branch}")
    if isinstance(data, list):
        mods = sorted(e["name"] for e in data
                      if isinstance(e, dict) and e.get("type") == "dir"
                      and e.get("name") and not e["name"].startswith("."))
        try:
            cf.write_text(json.dumps({"ts": ahora, "mods": mods}), encoding="utf-8")
        except OSError:
            pass
        return set(mods)
    return viejo
