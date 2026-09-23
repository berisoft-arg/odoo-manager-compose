# Generado por OMC | {{PROYECTO}} Odoo {{ODOO_VERSION}}
FROM {{ODOO_IMAGE}}
USER root
# 1) Sistema SIEMPRE antes del pip (orden vital para localizaciones AR):
#    git (URLs git+https en requirements) + paquetes de localización (ej python3-m2crypto).
#    M2Crypto solo funciona vía apt: por pip no compila en slim.
RUN apt-get update && apt-get install -y --no-install-recommends git{{APT_PKGS}} && rm -rf /var/lib/apt/lists/*
# 2) Recién después: dependencias Python de los módulos (Debian 12 / PEP 668: --break-system-packages)
COPY requirements-odoo.txt /tmp/requirements-odoo.txt
RUN pip install --no-cache-dir{{PIP_BREAK}} -r /tmp/requirements-odoo.txt
{{SECPY_BLOCK}}# Si check-deps reportó binarios (apt), descomenta y completa:
# RUN apt-get update && apt-get install -y --no-install-recommends <BINARIOS> && rm -rf /var/lib/apt/lists/*
USER odoo
