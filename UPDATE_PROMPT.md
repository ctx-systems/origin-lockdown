# Update prompt

Paste this into an AI coding agent (Claude Code, Codex, …) in a checkout of this repo, or
follow it by hand. It refreshes every IP list and keeps the README in sync.

---

You are updating the `origin-lockdown` repository. Its IP lists must match each provider's
**official** published source. Accuracy matters more than speed: a wrong list can lock
real users out of a website or let attackers bypass a firewall.

1. **Fetchable providers.** Run `python3 scripts/update_ips.py`. If it fails for a provider,
   open that provider's `doc_url` from `sources.json` and check whether the endpoint moved.
   Fix `sources.json` and re-run. Never hand-edit files of `method: "fetch"` providers.

2. **Manual providers** (`method: "manual"` in `sources.json`). For each:
   - Open `doc_url` (try appending `.md`, many doc sites serve Markdown).
   - Extract the IPv4 and IPv6 addresses the provider says to allow. Note any port changes.
   - Rewrite `ips/<id>-v4.txt` / `ips/<id>-v6.txt` (one entry per line, no comments) and the
     corresponding code block in `README.md`.
   - If the page now offers a machine-readable endpoint, switch the provider to
     `method: "fetch"` and add the endpoint.
   - If the page is gone or hides the IPs behind a login, do **not** delete the list. Flag it
     in your summary.

3. **Pending providers** (`method: "pending"`, e.g. LimesGuard). Check whether `doc_url` or the
   provider site now publishes ranges. If it does, add endpoints, switch to `fetch` and
   replace the "coming soon" note in the README.

4. **README.** Update the entry counts in the provider sections (`(585)` etc.) and the
   inline Cloudflare lists, and set "Last verified" at the top to today's date.

5. **Sanity checks before committing:**
   - `python3 -c "import ipaddress,sys; [ipaddress.ip_network(l.strip(), strict=False) for f in sys.argv[1:] for l in open(f) if l.strip()]" ips/*.txt`
   - Look at `git diff --stat ips/`. Large removals need an explanation from the provider's own
     source, not a guess.

6. **Report**: a short table with provider, what changed (+added/−removed) and source URL, plus
   anything you could not verify. Open a PR titled `Update IP lists YYYY-MM-DD`. Don't push to `main`.

Rules: official sources only (no forums, no third-party mirrors, no IPs from memory). Don't
invent providers' ports or behaviour. If unsure, leave it and say so.
