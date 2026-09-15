# Optimización gzip para {{PROYECTO}} (generado por OMC).
# Se monta en /etc/nginx/conf.d/gzip.conf: la imagen nginx lo incluye
# dentro del bloque http. Vale para el site día-1 (HTTP) y el final (HTTPS).
gzip on;
gzip_disable "msie6";
gzip_vary on;
gzip_proxied any;
gzip_comp_level 6;
gzip_buffers 16 8k;
gzip_http_version 1.1;
gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript image/x-icon image/bmp image/png image/jpg image/jpeg image/gif;
