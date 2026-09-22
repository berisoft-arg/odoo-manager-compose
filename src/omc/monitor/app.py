#!/usr/bin/env python3
"""Monitor web del asistente Odoo (SOLO lectura: contenedores + logs).

Uso:
  python3 web/app.py [--port 8765] [--host 127.0.0.1] [--token XYZ]
  # VPS: --host 0.0.0.0 SIEMPRE con --token largo (o env ODOO_WEB_TOKEN).
"""
"""Monitor web Odoo (Flask, SOLO lectura).

Uso:
  omc-monitor [--port 8765] [--host 127.0.0.1] [--token XYZ] [--fondo|--stop|--estado]
"""
import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

# Raíz de proyectos a monitorear (/opt por default, ver omc.core.projects_home).
try:
    from omc.core import projects_home as _projects_home

    BASE = _projects_home().resolve()
except Exception:  # noqa: BLE001  (standalone: fallback sin paquete)
    import os as _os

    _env = (_os.environ.get("OMC_PROJECTS", "") or _os.environ.get("OMC_HOME", "")
            or _os.environ.get("ODOO_CREATOR_HOME", ""))
    BASE = (Path(_env) if _env else Path("/opt")).resolve()

from flask import Flask, jsonify, render_template, request, abort  # noqa: E402

app = Flask(__name__)
TOKEN = ""


import logging

LOG = logging.getLogger("werkzeug")
LOG.disabled = True  # silenciar access-log (evita que ?token= quede en logs)

# caché simple para /api/metricas: 20s por proyecto (evita pegarle a PG cada segundo)
_METRIC_CACHE: dict = {}


def check_auth():
    tok = request.headers.get("X-Token", "")
    if not tok or tok != TOKEN:
        abort(401)


@app.before_request
def _auth():
    if request.path in ("/", "/login", "/favicon.ico") or request.path.startswith("/static"):
        return
    check_auth()


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/login")
def login():
    return render_template("index.html")


@app.get("/favicon.ico")
def favicon():
    return "", 204


def proyecto_valido(nombre: str) -> Path | None:
    d = (BASE / nombre).resolve()
    if not nombre or d != BASE and BASE not in d.parents:
        return None
    if not (d / "docker-compose.yml").exists():
        return None
    return d


@app.get("/api/proyectos")
def api_proyectos():
    out = []
    try:
        for d in sorted(BASE.iterdir()):
            if d.is_dir() and (d / "docker-compose.yml").exists():
                env = {}
                f = d / ".env"
                if f.exists():
                    for line in f.read_text().splitlines():
                        s = line.strip()
                        if s and not s.startswith("#") and "=" in s:
                            k, v = s.split("=", 1)
                            env[k.strip()] = v.strip()
                corriendo, total = 0, 0
                try:
                    r = subprocess.run(["docker", "compose", "ps", "--format", "json"],
                                       cwd=str(d), text=True, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, timeout=20)
                    for line in (r.stdout or "").splitlines():
                        if not line.strip():
                            continue
                        total += 1
                        try:
                            if json.loads(line).get("State", "").lower() == "running":
                                corriendo += 1
                        except ValueError:
                            pass
                except Exception:  # noqa: BLE001
                    pass
                estado = f"{corriendo}/{total} en marcha" if total else "apagado"
                out.append({"nombre": d.name,
                            "odoo": env.get("ODOO_VERSION", "?"),
                            "puerto": env.get("ODOO_PORT", "?"),
                            "dominio": env.get("DOMINIO", ""),
                            "estado": estado})
    except OSError:
        pass
    return jsonify(out)


@app.get("/api/contenedores")
def api_contenedores():
    try:
        r = subprocess.run(["docker", "ps", "--format", "json"], text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        conts = []
        for line in (r.stdout or "").splitlines():
            try:
                c = json.loads(line)
                conts.append({"nombre": c.get("Names", ""), "imagen": c.get("Image", ""),
                              "estado": c.get("State", ""), "puertos": c.get("Ports", "")})
            except ValueError:
                pass
        return jsonify(conts)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500


@app.get("/api/logs")
def api_logs():
    nombre = request.args.get("proyecto", "")
    servicio = request.args.get("servicio", "")
    tail = request.args.get("tail", "200")
    if servicio not in ("", "odoo", "db", "nginx"):
        return jsonify({"error": "servicio inválido (usa odoo, db o nginx)"}), 400
    d = proyecto_valido(nombre)
    if d is None:
        return jsonify({"error": "proyecto inválido"}), 400
    cmd = ["docker", "compose", "logs", "--tail", tail, "--no-color"]
    if servicio:
        cmd.append(servicio)
    try:
        r = subprocess.run(cmd, cwd=str(d), text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=30)
        return jsonify({"log": r.stdout or ""})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500


def leer_env(d: Path) -> dict:
    env = {}
    f = d / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def pg_exec(d: Path, db: str, sql: str, password: str):
    """Consulta SQL de SOLO lectura vía el contenedor db (timeout 25s)."""
    import os as _os
    env = dict(_os.environ, PGPASSWORD=password)
    r = subprocess.run(["docker", "compose", "exec", "-T", "db",
                        "psql", "-U", "odoo", "-d", db, "-tAX", "-c", sql],
                       cwd=str(d), text=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=25, env=env)
    if r.returncode != 0:
        return None
    return (r.stdout or "").strip()


def tam_dir(p: Path) -> int:
    total = 0
    try:
        for root, _dirs, files in os.walk(p):
            for f in files:
                try:
                    total += (Path(root) / f).stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def hum(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "?"
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.1f}{u}" if u != "B" else f"{int(n)}B"
        n /= 1024


@app.get("/api/metricas/<nombre>")
def api_metricas(nombre):
    now = time.time()
    cached = _METRIC_CACHE.get(nombre)
    if cached and now - cached[0] < 20:
        return jsonify(cached[1])
    d = proyecto_valido(nombre)
    if d is None:
        return jsonify({"error": "proyecto inválido"}), 400
    env = leer_env(d)
    pw = env.get("POSTGRES_PASSWORD", "odoo")
    m = {"proyecto": nombre}

    # --- Postgres (lecturas livianas) ---
    pg = {"ok": False}
    maxc = pg_exec(d, "postgres", "SHOW max_connections;", pw)
    if maxc is not None:
        try:
            pg["max_conn"] = int(maxc)
        except ValueError:
            pass
        n = pg_exec(d, "postgres", "SELECT count(*) FROM pg_stat_activity;", pw)
        try:
            pg["conexiones"] = int((n or "0").strip())
        except ValueError:
            pg["conexiones"] = None
        lentas = pg_exec(d, "postgres",
                         "SELECT pid||'|'||round(extract(epoch from now()-query_start))||'s|'||"
                         "left(regexp_replace(query,'\\s+',' ','g'),100) FROM pg_stat_activity "
                         "WHERE state='active' AND now()-query_start > interval '5 seconds' "
                         "AND pid<>pg_backend_pid() ORDER BY 1 DESC LIMIT 10;", pw)
        pg["lentas"] = [l for l in (lentas or "").splitlines() if l.strip()]
        bloq = pg_exec(d, "postgres", "SELECT count(*) FROM pg_locks WHERE NOT granted;", pw)
        try:
            pg["bloqueos"] = int((bloq or "0").strip())
        except ValueError:
            pass
        sizes = pg_exec(d, "postgres",
                        "SELECT datname||'|'||pg_database_size(datname) FROM pg_database "
                        "WHERE datistemplate=false;", pw)
        pg["bases"] = []
        if sizes:
            for line in sizes.splitlines():
                if "|" in line:
                    b, s = line.rsplit("|", 1)
                    try:
                        pg["bases"].append({"bd": b.strip(), "bytes": int(s.strip())})
                    except ValueError:
                        pass
            pg["bases"].sort(key=lambda x: -x["bytes"])
        # cron por BD con tablas odoo (ir.cron; en Odoo 18 el nombre es cron_name)
        pg["cron"] = []
        for b in [x["bd"] for x in pg["bases"] if x["bd"] not in ("postgres",)]:
            existe = pg_exec(d, b, "SELECT to_regclass('public.ir_cron')::text;", pw)
            if existe and "ir_cron" in existe:
                cols = pg_exec(d, b, "SELECT string_agg(column_name,',') "
                                     "FROM information_schema.columns "
                                     "WHERE table_name='ir_cron';", pw) or ""
                etiqueta = "name" if ",name," in f",{cols}," else (
                    "cron_name" if ",cron_name," in f",{cols}," else "id::text")
                det = pg_exec(d, b, f"SELECT id||'|'||left({etiqueta},40)||'|'||COALESCE(lastcall::text,'nunca')"
                                    " FROM public.ir_cron WHERE active ORDER BY nextcall NULLS LAST LIMIT 15;", pw)
                pg["cron"].append({"bd": b, "tareas": (det or "").splitlines()})
        pg["ok"] = True
    m["postgres"] = pg

    # --- crecimiento (historial local, sin cargar la BD) ---
    hist_f = _jobs_dir() / f"hist-{nombre}.json"
    hist = []
    try:
        if hist_f.exists():
            hist = json.loads(hist_f.read_text() or "[]")
    except ValueError:
        hist = []
    ahora = int(time.time())
    if pg.get("bases"):
        if not hist or ahora - hist[-1].get("ts", 0) > 3600:
            hist.append({"ts": ahora,
                         "sizes": {b["bd"]: b["bytes"] for b in pg["bases"]}})
            hist = hist[-90:]
            try:
                hist_f.parent.mkdir(parents=True, exist_ok=True)
                hist_f.write_text(json.dumps(hist), encoding="utf-8")
            except OSError:
                pass
    m["crecimiento"] = []
    base = next((h for h in reversed(hist[:-1])
                 if ahora - h.get("ts", 0) >= 20 * 3600), None)
    if base and pg.get("bases"):
        for b in pg["bases"]:
            antes = base["sizes"].get(b["bd"])
            if antes:
                m["crecimiento"].append({"bd": b["bd"], "delta": b["bytes"] - antes})

    # --- docker stats del proyecto ---
    stats = []
    try:
        r = subprocess.run(["docker", "stats", "--no-stream", "--format", "json"],
                           text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=25)
        for line in (r.stdout or "").splitlines():
            try:
                s = json.loads(line)
            except ValueError:
                continue
            if (s.get("Name", "") or "").startswith(f"{nombre}-") or \
               (s.get("Name", "") or "").startswith(f"{nombre}_"):
                stats.append({"nombre": s.get("Name", ""), "cpu": s.get("CPUPerc", ""),
                              "mem": s.get("MemUsage", ""), "memp": s.get("MemPerc", "")})
    except Exception:  # noqa: BLE001
        pass
    m["stats"] = stats

    # --- disco ---
    try:
        import shutil as _sh
        tot, usado, libre = _sh.disk_usage(d)
        m["disco"] = {"total": tot, "usado": usado, "libre": libre}
    except OSError:
        m["disco"] = {}
    m["backups_bytes"] = tam_dir(d / "backups")

    # --- último backup (scripts/backup.sh deja backups/<bd>_<fecha>/) ---
    m["backup"] = {}
    try:
        cands = [x for x in (d / "backups").iterdir() if x.is_dir()]
        if cands:
            ult = max(cands, key=lambda x: x.stat().st_mtime)
            ok = (ult / "db.dump").exists()
            m["backup"] = {"carpeta": ult.name,
                           "fecha": int(ult.stat().st_mtime),
                           "bytes": tam_dir(ult), "ok": ok}
    except OSError:
        pass

    # --- SSL (letsencrypt del proyecto) ---
    m["ssl"] = {}
    dom = env.get("DOMINIO", "")
    cert = d / "letsencrypt" / "live" / dom / "fullchain.pem" if dom else None
    if cert and cert.exists():
        try:
            r = subprocess.run(["openssl", "x509", "-enddate", "-noout", "-in", str(cert)],
                               text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, timeout=15)
            import datetime as _dt
            for line in (r.stdout or "").splitlines():
                if line.startswith("notAfter="):
                    fin = _dt.datetime.strptime(line[8:].strip(), "%b %d %H:%M:%S %Y %Z")
                    dias = (fin - _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)).days
                    m["ssl"] = {"dominio": dom, "dias": dias}
        except Exception:  # noqa: BLE001
            pass

    # --- AFIP WSAA (ARCA) por BD ---
    m["afip"] = []
    try:
        bds = (m.get("pg") or {}).get("bases") or []
        for bd in bds:
            try:
                r = subprocess.run(
                    ["docker", "compose", "exec", "-T", "db",
                     "psql", "-U", "odoo", "-d", bd,
                     "-At", "-c",
                     "SELECT crt FROM afipws_certificate WHERE state='confirmed' ORDER BY id DESC LIMIT 1;"],
                    cwd=str(d), text=True, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, timeout=15)
                crt = (r.stdout or "").strip()
                if r.returncode != 0 or not crt or "BEGIN CERTIFICATE" not in crt:
                    continue
                # alias
                ra = subprocess.run(
                    ["docker", "compose", "exec", "-T", "db",
                     "psql", "-U", "odoo", "-d", bd,
                     "-At", "-c",
                     "SELECT a.common_name || E'\t' || a.company_cuit || E'\t' || a.type "
                     "FROM afipws_certificate c JOIN afipws_certificate_alias a ON a.id=c.alias_id "
                     "WHERE c.state='confirmed' ORDER BY c.id DESC LIMIT 1;"],
                    cwd=str(d), text=True, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, timeout=15)
                alias = cuit = typ = ""
                if ra.returncode == 0 and ra.stdout:
                    parts = ra.stdout.strip().split("\t")
                    if len(parts) >= 3:
                        alias, cuit, typ = parts[0], parts[1], parts[2]
                import tempfile as _tf
                with _tf.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as tf:
                    tf.write(crt)
                    tf.flush()
                    tmp = tf.name
                try:
                    rr = subprocess.run(
                        ["openssl", "x509", "-enddate", "-noout", "-in", tmp],
                        text=True, stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, timeout=15)
                    import datetime as _dt2
                    dias = None
                    level = "ok"
                    not_after = ""
                    for line in (rr.stdout or "").splitlines():
                        if line.startswith("notAfter="):
                            not_after = line[9:].strip()
                            try:
                                fin = _dt2.datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
                                fin = fin.replace(tzinfo=_dt2.timezone.utc)
                                dias = (fin - _dt2.datetime.now(_dt2.timezone.utc)).days
                                if dias is not None:
                                    if dias <= 0:
                                        level = "vencido"
                                    elif dias <= 7:
                                        level = "critical"
                                    elif dias <= 30:
                                        level = "warn"
                            except Exception:  # noqa: BLE001
                                pass
                    if dias is not None:
                        m["afip"].append({"bd": bd, "alias": alias, "cuit": cuit,
                                           "type": typ, "dias": dias,
                                           "notAfter": not_after, "level": level})
                finally:
                    try:
                        import os as _os2
                        _os2.unlink(tmp)
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass

    # --- errores 5xx recientes en nginx (si existe) ---
    m["http_5xx"] = None
    try:
        r = subprocess.run(["docker", "compose", "logs", "--tail", "500", "--no-color", "nginx"],
                           cwd=str(d), text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=25)
        import re as _re
        n = len(_re.findall(r'"\s5\d\d\s', r.stdout or ""))
        if r.returncode == 0:
            m["http_5xx"] = n
    except Exception:  # noqa: BLE001
        pass

    _METRIC_CACHE[nombre] = (now, m)
    return jsonify(m)


def _runtime_dir() -> Path:
    """Dir de estado del monitor (pid/log). XDG, overridible con OMC_RUNTIME."""
    base = Path(os.environ.get("OMC_RUNTIME", Path.home() / ".local" / "share" / "omc"))
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return base


def _jobs_dir() -> Path:
    """Dir del historial de métricas. XDG, overridible con OMC_CACHE."""
    d = Path(os.environ.get("OMC_CACHE", Path.home() / ".cache" / "omc" / "jobs"))
    try:
        d.mkdir(parents=True, exist_ok=True)
        # migrar historial legacy (repo) una vez, sin pisar lo nuevo
        legacy = BASE / "web" / ".jobs"
        if legacy.is_dir() and not any(d.iterdir()):
            for f in sorted(legacy.glob("hist-*.json")):
                (d / f.name).write_bytes(f.read_bytes())
    except OSError:
        pass
    return d


PIDFILE = _runtime_dir() / "monitor.pid"
LOGFILE = _runtime_dir() / "monitor.log"
_PID_LEGACY = BASE / "web" / "monitor.pid"


def _leer_pidfile() -> tuple | None:
    """(pid, puerto, path) del pidfile nuevo o legacy. None si no hay."""
    for path in (PIDFILE, _PID_LEGACY):
        try:
            partes = path.read_text().strip().split()
            return int(partes[0]), (partes[1] if len(partes) > 1 else "?"), path
        except (OSError, ValueError):
            continue
    return None


def _es_nuestro_monitor(pid: int) -> bool:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmd = f.read().decode("utf-8", "replace")
            return "omc.monitor" in cmd or "app.py" in cmd
    except OSError:
        return False


def _limpiar_pidfile():
    for path in (PIDFILE, _PID_LEGACY):
        try:
            path.unlink()
        except OSError:
            pass


def pid_vivo() -> int | None:
    leido = _leer_pidfile()
    if not leido:
        return None
    pid, _puerto, _path = leido
    try:
        os.kill(pid, 0)
    except OSError:
        _limpiar_pidfile()  # proceso muerto: pidfile rancio
        return None
    if _es_nuestro_monitor(pid):
        return pid
    _limpiar_pidfile()  # PID reutilizado por otro proceso
    return None


def main():
    global TOKEN
    ap = argparse.ArgumentParser(description="Monitor web Odoo (solo lectura)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--token", default=os.environ.get("ODOO_WEB_TOKEN", ""))
    ap.add_argument("--fondo", action="store_true", help="Corre en fondo (libera la terminal)")
    ap.add_argument("--stop", action="store_true", help="Detiene el monitor en fondo")
    ap.add_argument("--estado", action="store_true", help="Muestra si hay monitor corriendo")
    args = ap.parse_args()
    if args.estado:
        pid = pid_vivo()
        print(f"Monitor en fondo: PID {pid}" if pid else "Monitor en fondo: detenido")
        return
    if args.stop:
        pid = pid_vivo()
        if not pid:
            print("No hay monitor en fondo (pidfile limpio).")
            return
        import signal as _sig
        try:
            os.kill(pid, _sig.SIGTERM)
            print(f"Monitor {pid} detenido.")
        except OSError as e:  # noqa: BLE001
            print(f"No se pudo detener: {e}")
        _limpiar_pidfile()
        return
    TOKEN = args.token or secrets.token_urlsafe(24)
    if args.host != "127.0.0.1" and not args.token and not os.environ.get("ODOO_WEB_TOKEN"):
        print("⚠ VPS expuesto con token aleatorio (guárdalo). Mejor: --token <largo> fijo.")
    if args.host == "0.0.0.0" and "gunicorn" not in sys.argv[0]:
        print("⚠ Monitor solo lectura: en VPS siempre detrás de reverse-proxy TLS (nginx/caddy) o VPN.")
        print("  Nunca expongas http://0.0.0.0 sin TLS a internet: el token viaja en claro.")
    if args.fondo:
        ya = pid_vivo()
        if ya:
            leido = _leer_pidfile()
            puerto_viejo = leido[1] if leido else "?"
            print(f"Ya hay monitor en fondo (PID {ya}, puerto {puerto_viejo}). --stop primero.")
            return
        log = open(LOGFILE, "a", encoding="utf-8")
        p = subprocess.Popen([sys.executable, "-m", "omc.monitor.app",
                              "--port", str(args.port), "--host", args.host,
                              "--token", TOKEN],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                             start_new_session=True, cwd=str(BASE))
        PIDFILE.write_text(f"{p.pid} {args.port}", encoding="utf-8")
        import time as _t
        _t.sleep(2)
        pid = pid_vivo()
        if not pid:
            # fallback: buscarlo por puerto
            print(f"Monitor lanzado en fondo. Revisa: curl http://{args.host}:{args.port}/")
        else:
            print(f"Monitor en fondo (PID {pid}). Abrir http://{args.host}:{args.port}  token: {TOKEN}")
            print("Para detener: omc-monitor --stop")
        return
    print(f"Monitor en http://{args.host}:{args.port}  token: {TOKEN}")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
