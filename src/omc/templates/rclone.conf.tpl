# rclone.conf de ejemplo para {{PROYECTO}} (Google Drive)
# 1) Instala rclone: https://rclone.org/install/
# 2) Opción A (recomendada): rclone config  -> crea remote "gdrive" y copia aquí el bloque [gdrive]
# 3) Opción B: edita este archivo con tu client_id / token
# NO commitees tokens reales a git.
[{{RCLONE_REMOTE}}]
type = drive
scope = drive.file
# client_id = TU_CLIENT_ID
# client_secret = TU_CLIENT_SECRET
# token = {"access_token":"...","token_type":"Bearer",...}
