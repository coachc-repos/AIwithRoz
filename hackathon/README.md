# Hackathon export

The self-contained app is [`hackathon-scriptcraft/`](../hackathon-scriptcraft/).

Copy that folder into your repo root, then follow its README (Azure login, `./setup-azure.sh`, `docker compose up`).

To produce a clean copy with no `.env`, caches, or local-only files:

```bash
./hackathon/export.sh /tmp/hackathon-scriptcraft
```

The script scans the copy and writes `/tmp/hackathon-scriptcraft.zip`.
