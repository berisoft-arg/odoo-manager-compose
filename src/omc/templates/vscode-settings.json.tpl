{
    "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
    "python.analysis.extraPaths": ["${workspaceFolder}/addons", "${workspaceFolder}/addons/custom", "${workspaceFolder}/addons/oca", "${workspaceFolder}/addons/adhoc"],
    "python.linting.enabled": true,
    "python.formatting.provider": "black",
    "editor.formatOnSave": true,
    "editor.rulers": [100],
    "files.exclude": {
        "**/__pycache__": true,
        "**/*.pyc": true,
        "**/.git": true
    },
    "search.exclude": {
        "**/addons/oca": true,
        "**/addons/adhoc": true,
        "**/__pycache__": true
    },
    // {{PROYECTO}} — Odoo {{ODOO_VERSION}} generado por OMC
    "odoo.version": "{{ODOO_VERSION}}"
}
