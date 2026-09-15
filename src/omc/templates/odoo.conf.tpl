; Proyecto: {{PROYECTO}} | Entorno: {{ENTORNO}} | Generado por omc
[options]
; El helper agrega aquí cada repo (sin symlinks): /mnt/extra-addons/<subdir>/<repo>
addons_path = {{ADDONS_PATH}}
data_dir = /var/lib/odoo
admin_passwd = {{ADMIN_PASSWD}}
db_host = db
db_port = 5432
db_user = odoo
db_password = {{PG_PASSWORD}}
db_maxconn = 64
workers = {{WORKERS}}
{{EXTRA_OPCIONES}}
; Sin logfile = log a stdout (ideal para `docker compose logs`)
; (no poner logfile = False, Odoo 19 lo rechaza)
; http_interface explícito para Docker (evita warning 20.0)
http_interface = 0.0.0.0
