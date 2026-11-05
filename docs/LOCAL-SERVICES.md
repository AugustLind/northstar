# Local AI and background services

Return to the [README](../README.md). Run commands from the repository root.

## Optional local AI

Install and start Ollama separately using its
[official instructions](https://docs.ollama.com/linux), then run:

```bash
bash scripts/setup-local-ai.sh
```

The helper pulls `qwen2.5:3b`. In Research settings, enable **Generate local AI
briefings**, or select another installed model. Model downloads and generation
need disk space, memory, and computing resources; they are not required for
computed research signals. The separate Oracle installer chooses a smaller
`qwen2.5:1.5b` model for its target VM.

Northstar sends bounded research/notebook context to the local Ollama endpoint
at `127.0.0.1:11434`. The model has no live web tool, and AI text cannot change
computed actions. For detailed context limits, see the
[technical reference](REFERENCE.md#free-local-ai).

## Linux user service

Stop a foreground copy before installing the service:

```bash
bash scripts/install-service.sh
```

This writes a unit under your user systemd configuration, enables it, and starts
it without requiring root. Existing units are not overwritten. To continue
across logout and start at boot, enable user lingering if permitted:

```bash
loginctl enable-linger "$USER"
```

Operations:

```bash
systemctl --user status northstar
journalctl --user -u northstar -f
systemctl --user restart northstar
systemctl --user disable --now northstar
```

The computer must remain awake and connected to fetch data. This installer does
not install or start Ollama. User service setup differs from the system service
created by the [Oracle installer](../DEPLOY.md); avoid running both against the
same checkout/database.
