import sys
import subprocess
from pathlib import Path

import pytest

# usa el paquete instalado/editable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _crt_fixture():
    # Cert real de demo17 (expira 2028) para test sin generar nuevo
    # Se usa solo como string que contiene BEGIN CERTIFICATE
    return Path("/tmp/demo17_crt.pem").read_text() if Path("/tmp/demo17_crt.pem").exists() else (
        "-----BEGIN CERTIFICATE-----\n"
        "MIIB\n"
        "-----END CERTIFICATE-----\n"
    )


def test_afip_monitor_mocks(monkeypatch, tmp_path):
    # Proyecto fake en OMC_PROJECTS
    # No usamos el monitor real con docker, solo testeamos el parsing del crt
    # Generamos un cert autofirmado de 5 días y verificamos que openssl lo lee
    import datetime as _dt
    key = tmp_path / "k.pem"
    crt = tmp_path / "c.pem"
    # openssl req -x509 -newkey rsa:1024 -nodes ... -days 5
    r = subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:1024", "-nodes",
         "-keyout", str(key), "-out", str(crt),
         "-days", "5", "-subj", "/CN=test-afip"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if r.returncode != 0:
        pytest.skip("sin openssl")
    # Verificar que nuestro código de monitor lo leería como dias ~5 y level critical
    rr = subprocess.run(["openssl", "x509", "-enddate", "-noout", "-in", str(crt)],
                        text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
    assert "notAfter=" in rr.stdout
    # Simular el cálculo de dias como lo hace app.py
    line = [l for l in rr.stdout.splitlines() if l.startswith("notAfter=")][0]
    fin = _dt.datetime.strptime(line[9:].strip(), "%b %d %H:%M:%S %Y %Z").replace(tzinfo=_dt.timezone.utc)
    dias = (fin - _dt.datetime.now(_dt.timezone.utc)).days
    assert 4 <= dias <= 6  # ~5 días
    # level según umbrales 30/7
    level = "vencido" if dias <= 0 else "critical" if dias <= 7 else "warn" if dias <= 30 else "ok"
    assert level == "critical"


def test_afip_endpoint_con_mock(monkeypatch, tmp_path):
    # Test del endpoint /api/metricas con mocks de docker/psql/openssl
    import datetime as _dt
    from omc.monitor import app as _app

    # Proyecto fake
    proj = tmp_path / "demo"
    proj.mkdir()
    (proj / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    (proj / ".env").write_text("ODOO_VERSION=17\nDOMINIO=demo.test\n", encoding="utf-8")
    (proj / "letsencrypt" / "live" / "demo.test").mkdir(parents=True, exist_ok=True)
    # No necesitamos cert SSL, afip es por BD

    monkeypatch.setenv("OMC_PROJECTS", str(tmp_path))
    # Forzar BASE a tmp_path (app usa projects_home)
    # Recargar app.BASE si es necesario (ya está cacheado, pero lo seteamos)
    _app.BASE = tmp_path.resolve()
    _app.TOKEN = "tok123"

    # Fecha futura 20 días para crt
    fut = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=20)
    not_after = fut.strftime("%b %d %H:%M:%S %Y GMT")
    fake_crt = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"

    vistas_db = []

    def _fake_run(cmd, **k):
        # psql para tamaños (pg bases, formato real datname|bytes)
        c = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        if "psql" in c and "pg_database_size" in c:
            return subprocess.CompletedProcess(
                cmd, 0, stdout="demo|123456\npostgres|7890\n", stderr="")
        if "psql" in c and "SELECT crt" in c:
            # registrar la BD pedida con -d: debe ser el nombre plano
            try:
                vistas_db.append(cmd[cmd.index("-d") + 1])
            except ValueError:
                pass
            return subprocess.CompletedProcess(cmd, 0, stdout=fake_crt, stderr="")
        if "psql" in c and "common_name" in c:
            return subprocess.CompletedProcess(cmd, 0, stdout="TestAFIP\t20202803874\thomologation", stderr="")
        if "openssl" in c and "x509" in c and "enddate" in c:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"notAfter={not_after}\n", stderr="")
        if "pg_isready" in c or "pg_database" in c:
            return subprocess.CompletedProcess(cmd, 0, stdout="demo\n", stderr="")
        if "docker" in c and "compose" in c:
            # para otras llamadas docker compose (psql, logs, etc.) devolver vacío ok
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        # fallback: llamar al real con timeout corto para no colgar
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("omc.monitor.app.subprocess.run", _fake_run)
    # También el import local de subprocess dentro de la función usa subprocess global, ya mockeado
    monkeypatch.setattr(subprocess, "run", _fake_run)

    with _app.app.test_client() as client:
        r = client.get("/api/metricas/demo", headers={"X-Token": "tok123"})
        assert r.status_code == 200
        data = r.get_json()
        # afip con UN elemento (incondicional: vacío sería el bug de la clave pg)
        assert "afip" in data
        assert isinstance(data["afip"], list)
        assert len(data["afip"]) == 1
        a = data["afip"][0]
        assert a["bd"] == "demo"
        assert a["alias"] == "TestAFIP"
        assert a["cuit"] == "20202803874"
        assert a["type"] == "homologation"
        # 20 días → warn
        assert 18 <= a["dias"] <= 22
        assert a["level"] == "warn"
        # -d con nombre plano de BD (nunca dict, nunca la BD postgres)
        assert vistas_db == ["demo"]
