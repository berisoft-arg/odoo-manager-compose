{
    "version": "2.0.0",
    "tasks": [
        {"label": "omc doctor", "type": "shell", "command": "omc doctor --proyecto ${workspaceFolder}", "problemMatcher": []},
        {"label": "omc update", "type": "shell", "command": "omc update ${input:mod} --proyecto ${workspaceFolder}", "problemMatcher": []},
        {"label": "omc test", "type": "shell", "command": "omc test ${input:mod} --proyecto ${workspaceFolder}", "problemMatcher": []},
        {"label": "logs odoo", "type": "shell", "command": "docker compose logs -f --tail=200 odoo", "options": {"cwd": "${workspaceFolder}"}, "problemMatcher": []}
    ],
    "inputs": [{"id": "mod", "type": "promptString", "description": "Módulo", "default": "custom"}]
    // {{PROYECTO}} — Odoo {{ODOO_VERSION}}
}
