# Agent notes

- To refresh IP lists, follow [UPDATE_PROMPT.md](UPDATE_PROMPT.md).
- `sources.json` is the registry. `ips/*.txt` files are data, one IP/CIDR per line.
- `scripts/update_ips.py` is standard-library Python. Keep it dependency-free.
- Only use official provider sources, never IPs from memory or third-party sites.
