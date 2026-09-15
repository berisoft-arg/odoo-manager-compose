"""Operaciones git (clone sparse, pull, ls-tree) con reintento simple de red."""
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .github import git_auth_args


def git_env() -> dict:
    """Entorno para git: jamás pedir usuario/password por terminal.

    Sin esto, ante un privado sin token (o token inválido) git se cuelga
    preguntando. Con esto falla rápido y mandan nuestros mensajes.
    """
    import os as _os
    return {**_os.environ, "GIT_TERMINAL_PROMPT": "0"}

SKIP_DIRS = {".github", ".oca", "setup", "docs", "migrations", ".copier-answers.yml"}


def run(cmd, cwd=None, capture=False, reintentos=0):
    """Ejecuta comando. Falla con sys.exit; reintenta N veces ante errores de red git."""
    intento = 0
    while True:
        r = subprocess.run(cmd, cwd=cwd, text=True, env=git_env(),
                           stdout=subprocess.PIPE if capture else None,
                           stderr=subprocess.PIPE if capture else None)
        if r.returncode == 0:
            return r.stdout.strip() if capture else ""
        out = (r.stderr or r.stdout or "")
        es_red = any(k in out.lower() for k in
                     ("could not resolve", "unable to access", "connection reset",
                      "timed out", "timeout", "temporary failure", "transfer closed"))
        if es_red and intento < reintentos:
            intento += 1
            time.sleep(2 * intento)
            continue
        sys.exit(f"Error: {' '.join(cmd)}\n{out[-2000:]}")


def git_red(repo_dir):
    """Prefijo git con auth del remote origin (fetch del promisor, pull, etc).

    El `-c http.extraHeader` de git_auth_args vale solo por invocación: el clon
    lo lleva, pero los sparse-checkout/reapply posteriores que bajan blobs del
    promisor también lo necesitan (si no, 401 en privados aunque el clon anduvo).
    """
    cfg = subprocess.run(["git", "remote", "get-url", "origin"], cwd=str(repo_dir),
                         text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         timeout=30)
    url = (cfg.stdout or "").strip()
    return ["git"] + git_auth_args(url)


def git_clone(url: str, branch: str, dest: str, reintentos: int = 1):
    run(["git"] + git_auth_args(url) + ["clone", "--filter=blob:none", "--sparse",
         "--depth", "1", "-b", branch, url, dest], reintentos=reintentos)


def git_pull(repo_dir: str, reintentos: int = 1):
    # el token se inyecta por http.extraHeader (nunca queda guardado)
    cfg = subprocess.run(["git", "remote", "get-url", "origin"], cwd=repo_dir,
                         text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    url = (cfg.stdout or "").strip()
    run(["git"] + git_auth_args(url) + ["pull", "--ff-only"], cwd=repo_dir,
        reintentos=reintentos)


def ramas_version(url: str):
    """Lista ramas X.0 disponibles en el remoto (para sugerir si falta la de tu Odoo)."""
    r = subprocess.run(["git"] + git_auth_args(url) + ["ls-remote", "--heads", url],
                       text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
                       env=git_env())
    if r.returncode != 0:
        return None
    import re
    ramas = sorted({m.group(1) for m in re.finditer(r"refs/heads/(\d+\.0)\s*$", r.stdout or "", re.M)},
                   key=lambda x: float(x))
    return ramas


def avisar_ramas(url: str, branch: str):
    """Si falla una rama, muestra qué ramas X.0 sí existen (o si la URL no anda)."""
    ramas = ramas_version(url)
    if ramas is None:
        print(f"  ⚠ No se pudo leer {url} (¿URL mal o repo privado sin GITHUB_TOKEN?).")
    elif branch not in ramas:
        hay = ", ".join(ramas) if ramas else "(ninguna X.0)"
        print(f"  ⚠ {url} no tiene rama {branch}. Disponibles: {hay}.")


def list_remote_topdirs(url: str, branch: str):
    """Devuelve (lista|None, unico:bool, ramas|None). Lista dirs top-level sin clonar completo.

    Si el repo trae __manifest__.py en la raíz, ES el módulo: lista vacía y unico=True.
    Si falla el clone, intenta sugerir ramas y devuelve (None, False, ramas|None).
    """
    tmp = Path(tempfile.mkdtemp(prefix="oca-ls-"))
    try:
        r = subprocess.run(
            ["git"] + git_auth_args(url) + ["clone", "--filter=blob:none", "--no-checkout",
             "--depth", "1", "-b", branch, url, str(tmp / "r")],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=git_env())
        if r.returncode != 0:
            err = ((r.stderr or "") + "\n" + (r.stdout or "")).lower()
            if "authentication failed" in err or "invalid username or password" in err \
                    or "could not read username" in err or " 403" in err:
                print("  ⚠ GitHub rechazó la autenticación: repo privado sin acceso.")
                print("    Revisa el token (menú 7: válido, con scope repo/Contents, sin expirar)")
                print("    o exporta GITHUB_TOKEN con uno válido y reintenta.")
                return None, False, None
            avisar_ramas(url, branch)
            return None, False, ramas_version(url)
        root = run(["git", "ls-tree", "--name-only", "HEAD"],
                   cwd=str(tmp / "r"), capture=True)
        if "__manifest__.py" in root.splitlines() or "__openerp__.py" in root.splitlines():
            return [], True, None
        out = run(["git", "ls-tree", "-d", "--name-only", "HEAD"],
                  cwd=str(tmp / "r"), capture=True)
        skip = {".github", ".oca", "setup", "docs", "migrations"}
        return sorted([d for d in out.splitlines()
                       if d and d not in skip and not d.startswith(".")]), False, None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
