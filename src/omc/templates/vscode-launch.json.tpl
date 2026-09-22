{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Odoo {{ODOO_VERSION}}: attach",
            "type": "debugpy",
            "request": "attach",
            "connect": {"host": "localhost", "port": 5678},
            "pathMappings": [{"localRoot": "${workspaceFolder}", "remoteRoot": "/mnt/extra-addons"}],
            "justMyCode": false
        },
        {
            "name": "Odoo {{ODOO_VERSION}}: shell",
            "type": "debugpy",
            "request": "launch",
            "program": "${workspaceFolder}/odoo-bin",
            "console": "integratedTerminal",
            "args": ["shell", "-d", "${input:db}"]
        }
    ],
    "inputs": [{"id": "db", "type": "promptString", "description": "Base Odoo", "default": "{{PROYECTO}}"}]
}
