"""Validación real con Docker: nginx -t, compose config y ruteo e2e.

Se saltean si no hay daemon (la suite unitaria corre en cualquier lado).
Limpian todo lo que crean (contenedores/redes con prefijo omctest-).
"""
import shutil
import subprocess
import time
import urllib.request

import pytest

NET = "omc-test-proxy"


def _run(cmd, **k):
    k.setdefault("stdout", subprocess.PIPE)
    k.setdefault("stderr", subprocess.PIPE)
    k.setdefault("text", True)
    k.setdefault("timeout", 60)
    return subprocess.run(cmd, **k)


def _docker_ok():
    if not shutil.which("docker"):
        return False
    try:
        if _run(["docker", "info"]).returncode != 0:
            return False
        return _run(["docker", "compose", "version"]).returncode == 0
    except Exception:  # noqa: BLE001
        return False


need_docker = pytest.mark.skipif(not _docker_ok(), reason="sin daemon docker")


def _site_dia1(dominio, host):
    from omc.core import render, template_text
    return render(template_text("nginx.conf.tpl"),
                  {"PROYECTO": "demo", "DOMINIO": dominio, "ODOO_HOST": host})


@need_docker
def test_nginx_t_multisitio(tmp_path):
    confd = tmp_path / "conf.d"
    confd.mkdir()
    (confd / "a.test.conf").write_text(_site_dia1("a.test", "a-odoo"),
                                       encoding="utf-8")
    (confd / "b.test.conf").write_text(_site_dia1("b.test", "b-odoo"),
                                       encoding="utf-8")
    from omc.core import render, template_text
    (confd / "gzip.conf").write_text(
        render(template_text("nginx-gzip.conf.tpl"), {"PROYECTO": "proxy"}),
        encoding="utf-8")
    r = _run(["docker", "run", "--rm",
              "--add-host", "a-odoo:127.0.0.1",
              "--add-host", "b-odoo:127.0.0.1",
              "-v", f"{confd}:/etc/nginx/conf.d/:ro",
              "nginx:alpine", "nginx", "-t"])
    assert r.returncode == 0, r.stderr
    assert "test is successful" in r.stderr


@need_docker
def test_nginx_t_dos_sites_proxy(tmp_path):
    # Dos sites proxy juntos: el resolver va por server (uno global duplicado
    # voltea el nginx entero con "directive is duplicate").
    from omc.core import render, template_text
    confd = tmp_path / "conf.d"
    confd.mkdir()
    for letra in ("a", "b"):
        (confd / f"{letra}.test.conf").write_text(
            render(template_text("proxy-site.conf.tpl"),
                   {"PROYECTO": f"s{letra}", "DOMINIO": f"{letra}.test",
                    "ODOO_HOST": f"be-{letra}"}),
            encoding="utf-8")
    (confd / "gzip.conf").write_text(
        render(template_text("nginx-gzip.conf.tpl"), {"PROYECTO": "proxy"}),
        encoding="utf-8")
    r = _run(["docker", "run", "--rm",
              "--add-host", "be-a:127.0.0.1",
              "--add-host", "be-b:127.0.0.1",
              "-v", f"{confd}:/etc/nginx/conf.d/:ro",
              "nginx:alpine", "nginx", "-t"])
    assert r.returncode == 0, r.stderr
    assert "test is successful" in r.stderr


@need_docker
def test_nginx_t_https_con_cert_autofirmado(tmp_path):
    if not shutil.which("openssl"):
        pytest.skip("sin openssl")
    from omc.core import render, template_text
    live = tmp_path / "letsencrypt" / "live" / "demo.test"
    live.mkdir(parents=True)
    r = _run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
              "-keyout", str(live / "privkey.pem"),
              "-out", str(live / "fullchain.pem"),
              "-days", "1", "-subj", "/CN=demo.test"])
    assert r.returncode == 0, r.stderr
    confd = tmp_path / "conf.d"
    confd.mkdir()
    (confd / "demo.test.conf").write_text(
        render(template_text("nginx-https.conf.tpl"),
               {"PROYECTO": "demo", "DOMINIO": "demo.test",
                "ODOO_HOST": "demo-odoo"}),
        encoding="utf-8")
    r = _run(["docker", "run", "--rm",
              "--add-host", "demo-odoo:127.0.0.1",
              "-v", f"{confd}:/etc/nginx/conf.d/:ro",
              "-v", f"{tmp_path / 'letsencrypt'}:/etc/letsencrypt:ro",
              "nginx:alpine", "nginx", "-t"])
    assert r.returncode == 0, r.stderr
    assert "test is successful" in r.stderr


@need_docker
def test_compose_config_proxy_y_sitio(tmp_path):
    import os
    from omc.compose import generar_proxy_compose, parchear_compose_a_proxy
    from omc.core import sin_renderizar
    proxy = tmp_path / "proxy"
    proxy.mkdir()
    (proxy / "docker-compose.yml").write_text(generar_proxy_compose(),
                                              encoding="utf-8")
    assert sin_renderizar((proxy / "docker-compose.yml").read_text(
        encoding="utf-8")) == []
    sitio = tmp_path / "tienda"
    sitio.mkdir()
    (sitio / "docker-compose.yml").write_text(
        "services:\n"
        "  db:\n"
        "    image: postgres:16\n"
        "  odoo:\n"
        "    image: odoo:18\n"
        "    restart: always\n"
        '    ports:\n      - "8070:8069"\n'
        "volumes:\n"
        "  odoo-db-data:\n",
        encoding="utf-8")
    (sitio / ".env").write_text("ODOO_PORT=8070\n", encoding="utf-8")
    parchear_compose_a_proxy(sitio, "tienda")
    env = dict(os.environ, POSTGRES_PASSWORD="x")
    for d in (proxy, sitio):
        r = _run(["docker", "compose", "-f", str(d / "docker-compose.yml"),
                  "config", "-q"], env=env)
        assert r.returncode == 0, r.stderr


@need_docker
def test_e2e_ruteo_por_subdominio(tmp_path):
    backends = {"a": "RESPUESTA-A", "b": "RESPUESTA-B"}
    creados = []

    def _dock(*args):
        r = _run(["docker", *args])
        assert r.returncode == 0, (args, r.stderr)
        return r

    try:
        # pre-limpieza defensiva (restos de corridas interrumpidas)
        for n in ("omctest-proxy", "omctest-backend-a", "omctest-backend-b"):
            _run(["docker", "rm", "-f", n])
        _run(["docker", "network", "rm", NET])
        _dock("network", "create", NET)
        creados.append(("network", NET))
        confd = tmp_path / "conf.d"
        confd.mkdir()
        for letra, texto in backends.items():
            nombre = f"omctest-backend-{letra}"
            be = tmp_path / f"be-{letra}"
            (be / "conf.d").mkdir(parents=True)
            (be / "conf.d" / "be.conf").write_text(
                "server {\n    listen 8069;\n    location / {\n"
                "        add_header Content-Type text/plain;\n"
                "        return 200 '" + texto + "';\n    }\n}\n",
                encoding="utf-8")
            _dock("run", "-d", "--name", nombre, "--network", NET,
                  "-v", f"{be / 'conf.d'}:/etc/nginx/conf.d/:ro",
                  "nginx:alpine")
            creados.append(("container", nombre))
            (confd / f"{letra}.test.conf").write_text(
                _site_dia1(f"{letra}.test", nombre), encoding="utf-8")
        from omc.core import render, template_text
        (confd / "gzip.conf").write_text(
            render(template_text("nginx-gzip.conf.tpl"), {"PROYECTO": "proxy"}),
            encoding="utf-8")

        def _ip(nombre):
            r = _run(["docker", "inspect", "-f",
                      "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                      nombre])
            assert r.returncode == 0, r.stderr
            return r.stdout.strip()

        def _esperar_backend(nombre):
            # Si el backend ya responde HTTP, su nombre está en el DNS
            # embebido; recién ahí el proxy puede resolver upstreams.
            ip = _ip(nombre)
            for _ in range(30):
                try:
                    req = urllib.request.Request(f"http://{ip}:8069/",
                                                 headers={"Host": "x.test"})
                    with urllib.request.urlopen(req, timeout=5) as r:
                        if r.status == 200:
                            return
                except Exception:  # noqa: BLE001
                    time.sleep(1)
            raise AssertionError(f"backend {nombre} sin respuesta")

        _esperar_backend("omctest-backend-a")
        _esperar_backend("omctest-backend-b")
        _dock("run", "-d", "--name", "omctest-proxy", "--network", NET,
              "-p", "18080:80",
              "-v", f"{confd}:/etc/nginx/conf.d/:ro",
              "nginx:alpine")
        creados.append(("container", "omctest-proxy"))

        def _get(host):
            url = "http://127.0.0.1:18080/"
            ultimo = None
            for _ in range(30):
                try:
                    req = urllib.request.Request(url, headers={"Host": host})
                    with urllib.request.urlopen(req, timeout=5) as r:
                        return r.read().decode()
                except Exception as e:  # noqa: BLE001
                    ultimo = repr(e)
                    time.sleep(1)
            logs = _run(["docker", "logs", "omctest-proxy"]).stderr[-2000:]
            raise AssertionError(f"sin respuesta para Host: {host}: {ultimo}\n{logs}")

        assert _get("a.test") == "RESPUESTA-A"
        assert _get("b.test") == "RESPUESTA-B"
    finally:
        for kind, name in reversed(creados):
            if kind == "container":
                _run(["docker", "rm", "-f", name])
            else:
                _run(["docker", "network", "rm", name])


@need_docker
def test_e2e_web_proxy_dia1(monkeypatch, tmp_path):
    """Flujo real `web --proxy` de punta a punta (certonly simulado en falla).

    Todo con docker de verdad salvo certonly (sin DNS no hay LE): el día 1
    HTTP queda ruteando por subdominio. Limpia todo al final.
    """
    import os
    from omc.core import puerto_en_uso
    from omc.flows import modo_configurar_web
    from types import SimpleNamespace
    if puerto_en_uso(80) or puerto_en_uso(443):
        pytest.skip("80/443 ocupados en este host")
    monkeypatch.setenv("OMC_PROJECTS", str(tmp_path))
    monkeypatch.delenv("OMC_HOME", raising=False)
    real_run = subprocess.run

    def _router(cmd, **k):
        if "certbot" in cmd:
            class _RC:
                returncode = 1
            return _RC()
        return real_run(cmd, **k)

    monkeypatch.setattr("omc.flows.subprocess.run", _router)
    sitio = tmp_path / "tienda"
    sitio.mkdir()
    be = tmp_path / "be"
    (be / "conf.d").mkdir(parents=True)
    (be / "conf.d" / "be.conf").write_text(
        "server {\n    listen 8069;\n    location / {\n"
        "        return 200 'TIENDA-OK';\n    }\n}\n",
        encoding="utf-8")
    (sitio / "docker-compose.yml").write_text(
        "services:\n"
        "  odoo:\n"
        "    image: nginx:alpine\n"
        "    restart: always\n"
        '    ports:\n      - "8070:8069"\n'
        "    volumes:\n"
        "      - ../be/conf.d:/etc/nginx/conf.d/:ro\n"
        "volumes:\n"
        "  odoo-db-data:\n",
        encoding="utf-8")
    (sitio / ".env").write_text(
        "ENTORNO=produccion\nODOO_VERSION=18\nODOO_IMAGE=odoo:18\nODOO_PORT=8070\n",
        encoding="utf-8")
    (sitio / "config").mkdir()
    (sitio / "config" / "odoo.conf").write_text("[options]\n", encoding="utf-8")
    proxy = tmp_path / "proxy"
    try:
        from omc.flows import run_proxy_init
        run_proxy_init()  # red omc-proxy real + nginx real en 80/443
        modo_configurar_web(SimpleNamespace(
            proyecto=str(sitio), dominio="a.test", email="t@t.com",
            staging=False, proxy=True, standalone=False, no_input=True))

        def _get(host):
            url = "http://127.0.0.1:80/"
            ultimo = None
            for _ in range(30):
                try:
                    req = urllib.request.Request(url, headers={"Host": host})
                    with urllib.request.urlopen(req, timeout=5) as r:
                        return r.read().decode()
                except Exception as e:  # noqa: BLE001
                    ultimo = repr(e)
                    time.sleep(1)
            raise AssertionError(f"sin respuesta: {ultimo}")

        assert _get("a.test") == "TIENDA-OK"
        conf = (proxy / "conf.d" / "a.test.conf").read_text(encoding="utf-8")
        assert "listen 443 ssl" not in conf  # día 1: certonly falló
        assert "resolver 127.0.0.11 valid=10s;" in conf
        assert "set $up tienda-odoo:8069;" in conf
        assert "upstream {" not in conf
        assert "DOMINIO=a.test" in (sitio / ".env").read_text(encoding="utf-8")
        assert "proxy_mode = True" in (sitio / "config" / "odoo.conf").read_text(
            encoding="utf-8")
    finally:
        _run(["docker", "compose", "-f", str(sitio / "docker-compose.yml"),
              "down"], env=dict(os.environ))
        _run(["docker", "compose", "-f", str(proxy / "docker-compose.yml"),
              "down"], env=dict(os.environ))
        _run(["docker", "network", "rm", "omc-proxy"])


@need_docker
def test_e2e_backend_caido_no_tumba_al_resto(monkeypatch, tmp_path):
    """Aislamiento: con resolver+variable, parar un backend no voltea al proxy.

    Recarga OK con un upstream irresoluble; el site sano 200, el caído 5xx.
    """
    import os
    from omc.core import puerto_en_uso, render, template_text
    if puerto_en_uso(80) or puerto_en_uso(443):
        pytest.skip("80/443 ocupados en este host")
    monkeypatch.setenv("OMC_PROJECTS", str(tmp_path))
    monkeypatch.delenv("OMC_HOME", raising=False)
    real_run = subprocess.run

    def _router(cmd, **k):
        if "certbot" in cmd:
            class _RC:
                returncode = 1
            return _RC()
        return real_run(cmd, **k)

    monkeypatch.setattr("omc.flows.subprocess.run", _router)
    confd = tmp_path / "proxy" / "conf.d"

    def _be(letra, texto):
        be = tmp_path / f"be-{letra}"
        (be / "conf.d").mkdir(parents=True)
        (be / "conf.d" / "be.conf").write_text(
            "server {\n    listen 8069;\n    location / {\n"
            "        return 200 '" + texto + "';\n    }\n}\n",
            encoding="utf-8")
        r = real_run(["docker", "run", "-d", "--name", f"omctest-be-{letra}",
                      "--network", "omc-proxy",
                      "-v", f"{be / 'conf.d'}:/etc/nginx/conf.d/:ro",
                      "nginx:alpine"],
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        time.sleep(2)
        st = real_run(["docker", "inspect", "-f", "{{.State.Status}}",
                       f"omctest-be-{letra}"],
                      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                      text=True, timeout=60)
        assert st.stdout.strip() == "running", st.stderr

    def _code(host):
        import urllib.error
        req = urllib.request.Request("http://127.0.0.1:80/",
                                     headers={"Host": host})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, ""

    try:
        from omc.flows import run_proxy_init
        run_proxy_init()
        for letra, texto in (("a", "A-OK"), ("b", "B-OK")):
            _be(letra, texto)
            (confd / f"{letra}.test.conf").write_text(
                render(template_text("proxy-site.conf.tpl"),
                       {"PROYECTO": f"s{letra}", "DOMINIO": f"{letra}.test",
                        "ODOO_HOST": f"omctest-be-{letra}"}),
                encoding="utf-8")
        r = real_run(["docker", "compose", "exec", "nginx", "nginx", "-s",
                      "reload"],
                     cwd=str(tmp_path / "proxy"),
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        time.sleep(3)

        def _code_ok(host, texto, tries=15):
            ultimo = (None, "")
            for _ in range(tries):
                ultimo = _code(host)
                if ultimo == (200, texto):
                    return ultimo
                time.sleep(1)
            return ultimo

        assert _code_ok("a.test", "A-OK") == (200, "A-OK")
        # parar un backend: el reload SIGUE ok y el otro site ni se entera
        real_run(["docker", "stop", "omctest-be-a"],
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                 timeout=60)
        r = real_run(["docker", "compose", "exec", "nginx", "nginx", "-s",
                      "reload"],
                     cwd=str(tmp_path / "proxy"),
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     text=True, timeout=60)
        assert r.returncode == 0, r.stderr  # con upstream estático fallaría acá
        time.sleep(3)
        assert _code_ok("b.test", "B-OK") == (200, "B-OK")
        for _ in range(5):
            code_a, _ = _code("a.test")
            assert code_a >= 500  # solo su site cae
            time.sleep(1)
    finally:
        for n in ("omctest-be-a", "omctest-be-b"):
            _run(["docker", "rm", "-f", n])
        _run(["docker", "compose", "-f",
              str(tmp_path / "proxy" / "docker-compose.yml"),
              "down"], env=dict(os.environ))
        _run(["docker", "network", "rm", "omc-proxy"])
