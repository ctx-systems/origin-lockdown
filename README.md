# origin-lockdown

**Put your server behind a proxy, then make sure the proxy is the only way in.**

A CDN or web shield (Cloudflare, bunny.net, LimesGuard, Fastly, …) only protects you
if attackers can't skip it. Once your origin IP leaks (old DNS records, mail headers,
certificate transparency logs, Shodan scans), anyone can send requests straight to
the server and bypass the WAF, rate limits, bot protection and DDoS mitigation you
pay for.

This repo collects:

- **IP ranges** for proxies/CDNs and for server-control panels, as plain text files in
  [`ips/`](ips/). A script and a weekly GitHub Action keep them up to date.
- **Instructions** for locking down an origin with `ufw`, `nftables`, nginx, and cloud
  firewalls, plus provider-specific notes.

> Last verified: **2026-11-02**. Fetched lists are refreshed automatically (see
> [Keeping lists up to date](#keeping-lists-up-to-date)). Lists marked *manual* are
> copied from a doc page, so check the linked source before you rely on them.

---

## Contents

- [The model](#the-model)
- [Step-by-step lockdown](#step-by-step-lockdown)
  - [ufw](#ufw)
  - [nftables](#nftables)
  - [nginx (real IP + allow-only)](#nginx-real-ip--allow-only)
  - [Cloud firewalls](#cloud-firewalls)
  - [Stronger than IP lists](#stronger-than-ip-lists)
  - [SSH lockdown](#ssh-lockdown) (your IP only, Tailscale, WireGuard)
- [Proxies & web shields](#proxies--web-shields)
  - [Cloudflare](#cloudflare) · [bunny.net](#bunnynet) · [LimesGuard](#limesguard) ·
    [Fastly](#fastly) · [Amazon CloudFront](#amazon-cloudfront) · [QUIC.cloud](#quiccloud) ·
    [Sucuri](#sucuri)
- [Server panels (SSH / agent access)](#server-panels-ssh--agent-access)
  - [SpinupWP](#spinupwp) · [Ploi](#ploi) · [GridPane](#gridpane) ·
    [Laravel Forge](#laravel-forge) · [RunCloud](#runcloud) · [Cloudways](#cloudways)
- [Keeping lists up to date](#keeping-lists-up-to-date)
- [Contributing](#contributing)

---

## The model

| Port | Who may connect | Lists |
|---|---|---|
| `80`, `443` | Your proxy / CDN only | `ips/<proxy>-v4.txt`, `-v6.txt` |
| `22` (or your SSH port) | You (your IP, or only over Tailscale/WireGuard, see [SSH lockdown](#ssh-lockdown)) + your control panel | `ips/<panel>-*.txt` |
| Panel agent ports (e.g. RunCloud `34210`) | That panel only | `ips/<panel>-*.txt` |
| Everything else | Nobody | — |

Things to remember:

1. **Allow IPv6 too.** Most proxies connect to your origin over IPv6 if the server has an
   AAAA record or a public v6 address. If you only allow v4 ranges, half your traffic fails.
2. **Restore the real visitor IP.** Behind a proxy every request appears to come from the
   proxy. Configure your web server (`set_real_ip_from` / `mod_remoteip`), or rate limits,
   fail2ban and logs will treat the CDN as a single attacker.
3. **Lists change.** Pin to these files and refresh them on a schedule, not once by hand.
4. **Outbound traffic doesn't need these rules.** They only restrict *inbound* connections.
5. **Don't lock yourself out.** Add your own SSH allow rule *before* enabling a default-deny
   policy, and keep a provider console (VNC/rescue) available.

## Step-by-step lockdown

Clone the repo on the server (or copy the `ips/` files you need):

```bash
git clone https://github.com/ctx-systems/origin-lockdown.git /opt/origin-lockdown
cd /opt/origin-lockdown
```

### ufw

```bash
# 1. yourself first
ufw allow from 203.0.113.10 to any port 22 proto tcp comment 'me'

# 2. your panel (example: SpinupWP)
scripts/ufw-allow.sh --ports 22 --apply ips/spinupwp-v4.txt ips/spinupwp-v6.txt

# 3. your proxy on 80/443 (example: Cloudflare)
scripts/ufw-allow.sh --ports 80,443 --apply ips/cloudflare-v4.txt ips/cloudflare-v6.txt

# 4. remove any generic "allow 80/443 from anywhere" rules
ufw delete allow 80/tcp; ufw delete allow 443/tcp
ufw delete allow 'Nginx Full' 2>/dev/null || true

# 5. default deny inbound
ufw default deny incoming
ufw enable
```

Run without `--apply` to print the commands instead of executing them. Rules are tagged
with `comment origin-lockdown:<list>`, so you can find them again (`ufw status | grep origin-lockdown`).

> **Docker caveat:** published Docker ports (`-p 80:80`) skip ufw because Docker writes its
> own iptables rules. Filter in the `DOCKER-USER` chain instead, or use a cloud firewall.

### nftables

For big lists (bunny.net has ~900 entries) a named set beats hundreds of ufw rules:

```bash
cat > /etc/nftables.d/origin-lockdown.nft <<EOF
table inet origin_lockdown {
  set proxy_v4 { type ipv4_addr; flags interval; elements = { $(paste -sd, ips/bunny-cdn-v4.txt) } }
  set proxy_v6 { type ipv6_addr; flags interval; elements = { $(paste -sd, ips/bunny-cdn-v6.txt) } }
  chain input {
    type filter hook input priority -10; policy accept;
    tcp dport { 80, 443 } ip  saddr != @proxy_v4 drop
    tcp dport { 80, 443 } ip6 saddr != @proxy_v6 drop
  }
}
EOF
nft -f /etc/nftables.d/origin-lockdown.nft
```

Re-run the same command after updating the lists. `nft -f` replaces the table atomically,
so there is no window where the rules are missing.

### nginx (real IP + allow-only)

Even with a firewall in place, nginx needs to know which proxy header carries the visitor IP:

```bash
scripts/nginx-snippet.sh CF-Connecting-IP ips/cloudflare-v4.txt ips/cloudflare-v6.txt \
  > /etc/nginx/conf.d/realip-cloudflare.conf
nginx -t && systemctl reload nginx
```

| Proxy | Real-IP header |
|---|---|
| Cloudflare | `CF-Connecting-IP` |
| bunny.net | `X-Forwarded-For` (or `X-Real-IP`) |
| Fastly | `Fastly-Client-IP` |
| CloudFront | `CloudFront-Viewer-Address` (needs an origin request policy) or `X-Forwarded-For` |
| QUIC.cloud | `X-Forwarded-For` |
| Sucuri | `X-Sucuri-ClientIP` |
| LimesGuard | `X-Limes-Client-Ip` |

If you can't touch the firewall (shared hosting, some managed panels), add `--allow-only`.
The script then also prints a `geo` block, and `return 444` drops non-proxy requests at
the HTTP layer. This is weaker than a firewall (the TLS handshake still happens) but much
better than nothing.

Apache: use `mod_remoteip` with `RemoteIPHeader` and one `RemoteIPTrustedProxy` line per range.

### Cloud firewalls

A provider-level firewall drops traffic before it reaches your VM. It also covers the
Docker caveat and doesn't use the server's CPU during a flood. Most providers have a rule
limit, so the big lists may need to be split up or summarised:

| Provider | Where | Notes |
|---|---|---|
| Hetzner Cloud | Firewalls → inbound rules | One rule takes many source IPs. Fits Cloudflare easily; bunny.net CDN may hit per-firewall limits. |
| DigitalOcean | Networking → Firewalls | Source limits apply per firewall. Check before importing bunny.net-sized lists. |
| AWS | Security groups | Use the managed prefix list `com.amazonaws.global.cloudfront.origin-facing` instead of copying ranges. |
| Vultr | Firewall groups | Also add panel IPs under *API Access Control* if a panel creates servers for you. |

### Stronger than IP lists

IP allow-lists say "this came from *a* Cloudflare/bunny customer", not "this came from
*your* zone". Anyone can put their own Cloudflare zone in front of your IP. To close that
gap, also do one of these:

- **Secret header**: have the proxy add `X-Origin-Auth: <long random>` and reject requests
  without it (bunny.net Edge Rules, Cloudflare Transform Rules, CloudFront custom origin headers).
- **Authenticated Origin Pulls / mTLS**: Cloudflare can present a client cert that nginx verifies
  (`ssl_verify_client on`).
- **No public ingress**: Cloudflare Tunnel (`cloudflared`) or a similar tunnel. The origin opens an
  outbound connection, so you can close 80/443 entirely.

### SSH lockdown

Port 22 open to the world means a constant stream of brute-force attempts, and one weak
password or leaked key away from a full compromise. Pick one of these, from simplest to strongest:

| Option | Good when | Public port 22? |
|---|---|---|
| Allow only your IP | You have a static IP (office, fixed-line ISP) | Open to your IP + panel IPs |
| Tailscale | Your IP changes, you have several people or servers | Closed (except panel IPs) |
| WireGuard | You want no third party involved | Closed, only UDP 51820 open |
| Bastion / jump host | Many servers, one audited entry point | Open to the bastion only |

Whatever you pick, **harden sshd too**. In `/etc/ssh/sshd_config.d/10-lockdown.conf`:

```
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
```

Then `sshd -t && systemctl reload ssh`. Test from a **second** terminal before you close the
first. Add fail2ban or CrowdSec if port 22 stays public in any form.

> **Using a panel?** SpinupWP, Ploi, GridPane, Forge and RunCloud SSH in over the public
> address, so keep allowing their IPs (see [Server panels](#server-panels-ssh--agent-access)) on
> top of whichever option you choose.

#### Allow only your IP

```bash
ufw allow from 203.0.113.10 to any port 22 proto tcp comment 'me'
ufw delete allow OpenSSH 2>/dev/null; ufw delete allow 22/tcp 2>/dev/null
```

Find your IP with `curl -4 ifconfig.me` (and `curl -6 ifconfig.me` if you have IPv6). If it
changes, you're locked out until you fix the rule from your provider's console. Set the same
rule in the [cloud firewall](#cloud-firewalls) as a safety net.

#### Tailscale

[Tailscale](https://tailscale.com/kb/1017/install) builds a private WireGuard network between your
devices and servers. It works behind NAT without opening any inbound port, and your home IP can
change freely.

```bash
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up                       # log in with the printed URL

# allow SSH only over the tailnet, then close it publicly
ufw allow in on tailscale0 to any port 22 proto tcp comment 'ssh via tailscale'
ufw delete allow OpenSSH 2>/dev/null; ufw delete allow 22/tcp 2>/dev/null
```

Then connect with `ssh user@<server-tailscale-name>` or its `100.x.y.z` address. Optional extras:

- `tailscale up --ssh` enables [Tailscale SSH](https://tailscale.com/kb/1193/tailscale-ssh): login
  is granted by your tailnet ACLs instead of `authorized_keys`.
- Use [ACLs / grants](https://tailscale.com/kb/1018/acls) so only admins can reach port 22 on servers.
- Turn off [key expiry](https://tailscale.com/kb/1028/key-expiry) for servers, or they drop off the
  tailnet when the key expires.
- To avoid a third-party control plane, [Headscale](https://github.com/juanfont/headscale) is a
  self-hosted alternative.

#### WireGuard

Plain WireGuard, no account needed. One UDP port stays open, and WireGuard doesn't answer
packets that aren't from a known key, so to a scanner the port looks closed.

On the server:

```bash
apt install wireguard
wg genkey | tee /etc/wireguard/server.key | wg pubkey > /etc/wireguard/server.pub
chmod 600 /etc/wireguard/server.key

cat > /etc/wireguard/wg0.conf <<EOF
[Interface]
Address    = 10.66.0.1/24
ListenPort = 51820
PrivateKey = $(cat /etc/wireguard/server.key)

[Peer]   # your laptop
PublicKey  = <laptop public key>
AllowedIPs = 10.66.0.2/32
EOF

systemctl enable --now wg-quick@wg0
ufw allow 51820/udp comment 'wireguard'
ufw allow in on wg0 to any port 22 proto tcp comment 'ssh via wireguard'
ufw delete allow OpenSSH 2>/dev/null; ufw delete allow 22/tcp 2>/dev/null
```

On your laptop (`wg-quick up ./server.conf`, or import it in the WireGuard app):

```ini
[Interface]
Address    = 10.66.0.2/32
PrivateKey = <laptop private key>

[Peer]
PublicKey  = <server public key>
Endpoint   = <server public ip>:51820
AllowedIPs = 10.66.0.1/32         # only the server, not all your traffic
PersistentKeepalive = 25
```

Then `ssh user@10.66.0.1`. With more than a couple of servers, give each its own address in
the same range, or use Tailscale/Headscale so you don't have to manage keys by hand.

#### Don't lock yourself out

- Add the new allow rule **before** removing the old one, and keep an existing SSH session open
  while you test.
- Know where your provider's web console / rescue system is (Hetzner Console, DigitalOcean
  Droplet Console, …). It works even when the firewall drops everything.
- If you use a tunnel, make sure it starts on boot (`systemctl is-enabled tailscaled` / `wg-quick@wg0`).

---

## Proxies & web shields

### Cloudflare

Source: <https://www.cloudflare.com/ips/> · Machine-readable: `https://www.cloudflare.com/ips-v4`,
`https://www.cloudflare.com/ips-v6`, `https://api.cloudflare.com/client/v4/ips` (JSON, includes an `etag`)
· Files: [`ips/cloudflare-v4.txt`](ips/cloudflare-v4.txt), [`ips/cloudflare-v6.txt`](ips/cloudflare-v6.txt)

<details><summary>IPv4 (15)</summary>

```
173.245.48.0/20
103.21.244.0/22
103.22.200.0/22
103.31.4.0/22
141.101.64.0/18
108.162.192.0/18
190.93.240.0/20
188.114.96.0/20
197.234.240.0/22
198.41.128.0/17
162.158.0.0/15
104.16.0.0/13
104.24.0.0/14
172.64.0.0/13
131.0.72.0/22
```
</details>

<details><summary>IPv6 (7)</summary>

```
2400:cb00::/32
2606:4700::/32
2803:f800::/32
2405:b500::/32
2405:8100::/32
2a06:98c0::/29
2c0f:f248::/32
```
</details>

Notes: Cloudflare only proxies the [supported ports](https://developers.cloudflare.com/fundamentals/reference/network-ports/)
(80, 443, 8080, 8443, 2053, …), so SSH and other ports still need their own rules. Use
`CF-Connecting-IP` for the real IP. For stronger origin protection see
[Authenticated Origin Pulls](https://developers.cloudflare.com/ssl/origin-configuration/authenticated-origin-pull/)
and [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/).

### bunny.net

**CDN edge servers** (these are what connect to your origin for a Pull Zone)

Source: <https://bunny.net/docs/cdn/connectivity> · Machine-readable:
`https://bunnycdn.com/api/system/edgeserverlist/plain` (IPv4, text),
`https://bunnycdn.com/api/system/edgeserverlist` (IPv4, JSON),
`https://bunnycdn.com/api/system/edgeserverlist/ipv6` (IPv6, JSON)
· Files: [`ips/bunny-cdn-v4.txt`](ips/bunny-cdn-v4.txt) (585), [`ips/bunny-cdn-v6.txt`](ips/bunny-cdn-v6.txt) (321)

**Magic Containers nodes** (outbound IPs of containers you run on bunny.net, e.g. to allow
them into your database)

Source: <https://bunny.net/docs/magic-containers/ip-addresses> · Machine-readable:
`https://api.bunny.net/mc/nodes/plain` (text), `https://api.bunny.net/mc/nodes` (JSON, paginated with `cursor`)
· File: [`ips/bunny-magic-containers-v4.txt`](ips/bunny-magic-containers-v4.txt) (135)

Notes: bunny.net lists individual edge IPs rather than ranges, and the list changes often
(bunny calls it "dynamic"). Refresh at least daily, or use the secret-header approach
via an Edge Rule. You can also limit which IP family a zone uses with
[IP Family Policy](https://bunny.net/docs/cdn/ip-family-policy).

### LimesGuard

European web shield by [ctx-systems](https://github.com/ctx-systems), running on EU infrastructure.

Source: <https://limesguard.eu/docs/lock-your-server> · Machine-readable:
`https://limesguard.eu/api/pub/edge-info` (JSON: `egress_ips`, plus `edge_hostname` to point DNS at)
· Files: [`ips/limesguard-v4.txt`](ips/limesguard-v4.txt), [`ips/limesguard-v6.txt`](ips/limesguard-v6.txt)

```
178.104.30.200
2a01:4f8:1c19:865d::1
```

Notes: every request Limes forwards carries `X-Limes-Origin-Key` with your site's key (see the
console → your site → *Origin key*). Check that header on the server as well as firewalling to
the IPs above. The site page in the console runs an origin lockdown check for you. Limes announces
address changes in advance.

#### What can I do now, before LimesGuard is widely available?

LimesGuard is still rolling out. In the meantime, you can protect your site today with:

- **[Cloudflare](#cloudflare)**: the free plan already includes a proxy, DDoS protection and a basic WAF.
  Lock your server to [the Cloudflare ranges](#cloudflare). For the strongest setup, add
  Authenticated Origin Pulls or use a Cloudflare Tunnel.
- **[bunny.net](#bunnynet) with Bunny Shield**: an EU-based CDN with a WAF, rate limiting and DDoS
  protection on top of a Pull Zone. Lock your server to [the bunny.net edge list](#bunnynet) and add
  a secret header via an Edge Rule.

Whichever you choose, the lockdown steps in this repo stay the same. Moving to LimesGuard later
means swapping one IP list for another and changing the header you check.

### Fastly

Machine-readable: `https://api.fastly.com/public-ip-list` (JSON: `addresses` and `ipv6_addresses`)
· Files: [`ips/fastly-v4.txt`](ips/fastly-v4.txt) (21), [`ips/fastly-v6.txt`](ips/fastly-v6.txt) (3)

Real IP header: `Fastly-Client-IP`.

### Amazon CloudFront

Source: <https://docs.aws.amazon.com/vpc/latest/userguide/aws-ip-ranges.html> · Machine-readable:
`https://ip-ranges.amazonaws.com/ip-ranges.json` filtered on `service == "CLOUDFRONT_ORIGIN_FACING"`
· Files: [`ips/cloudfront-v4.txt`](ips/cloudfront-v4.txt) (49), [`ips/cloudfront-v6.txt`](ips/cloudfront-v6.txt) (38)

On AWS, don't copy ranges. Reference the managed prefix lists
`com.amazonaws.global.cloudfront.origin-facing` and `com.amazonaws.global.ipv6.cloudfront.origin-facing`
in your security group. Note that the plain `CLOUDFRONT` service in `ip-ranges.json` also
includes viewer-facing edges, which is far too broad. Use `CLOUDFRONT_ORIGIN_FACING`.

### QUIC.cloud

The LiteSpeed CDN, popular with WordPress sites running LiteSpeed Cache.

Source: <https://quic.cloud/ips> · Machine-readable: `https://quic.cloud/ips?json`
· File: [`ips/quic-cloud-v4.txt`](ips/quic-cloud-v4.txt) (152)

### Sucuri

Sucuri doesn't publish a single range list. The addresses that connect to your origin are
shown per site in the Sucuri dashboard under *Firewall → Settings → Firewall Bypass*. Copy
those into your own list file, and verify `X-Sucuri-ClientIP` only when the TCP peer is one of them.

---

## Server panels (SSH / agent access)

These panels SSH into your server (or talk to an agent on it). If you restrict SSH, allow
their IPs or the panel breaks: provisioning, deploys and SSL renewals fail.

### SpinupWP

Source: <https://spinupwp.com/doc/whitelisting-ip-addresses/> (*manual*) · Port: `22`
· Files: [`ips/spinupwp-v4.txt`](ips/spinupwp-v4.txt), [`ips/spinupwp-v6.txt`](ips/spinupwp-v6.txt)

```
67.205.131.221      2604:a880:400:d0::1720:8001
67.205.148.70       2604:a880:400:d0::db3:f001
68.183.120.65       2604:a880:400:d0::db7:8001
192.34.58.2         2604:a880:400:d1::9b0:c001
157.245.128.167     2604:a880:400:d0::18f7:4001
104.248.115.117     2604:a880:400:d0::18f8:2001
157.245.82.51       2604:a880:400:d1::a9c:2001
```

SpinupWP says "this list will definitely be updated in the future" and runs an
[email list for IP changes](https://spinupwp.com/doc/whitelisting-ip-addresses/). Subscribe to it.

### Ploi

Source: <https://ploi.io/documentation/introduction/ploi-ip-for-whitelisting> (*manual*) · Port: `22`
(plus 80/443 if you firewall those)

- **Worker IPs** (needed for SSH) are only shown when you're **logged in** to ploi.io, so they
  aren't mirrored here. Easiest route: in Ploi, open your server → *Network* and allow the
  worker IPs with one click.
- **Uptime monitor IPs** are public: [`ips/ploi-uptime-v4.txt`](ips/ploi-uptime-v4.txt),
  [`ips/ploi-uptime-v6.txt`](ips/ploi-uptime-v6.txt)

```
85.9.214.127    2a04:3544:1000:1510:445b:ceff:feb7:1f38   Amsterdam
94.237.51.22    2a04:3541:1000:500:445b:ceff:feb7:51af    London
209.50.49.15    2605:7380:1000:1310:445b:ceff:feb7:74f5   Chicago
95.111.198.27   2a04:3543:1000:2310:445b:ceff:feb7:7d18   Singapore
```

Ploi Cloud (the managed platform) publishes *outbound* app ranges through an authenticated API:
`GET /api/v1/cluster/ip-ranges`. See [the docs](https://ploi.cloud/documentation/security/api-ip-ranges.md).

### GridPane

Source: <https://gridpane.com/kb/whitelisting-gridpane-at-your-server-providers/> (*manual*) · Port: `22`
· File: [`ips/gridpane-v4.txt`](ips/gridpane-v4.txt)

```
35.199.11.215
130.211.115.235
35.245.53.150
34.105.87.182
```

If you use DigitalOcean or Vultr cloud firewalls, allow these there too. On Vultr, also add
them under *API Access Control*. GridPane Failover also needs the source and destination
servers to reach each other.

### Laravel Forge

Source: <https://laravel.com/forge/docs/introduction#laravel-forge-ip-addresses> · Machine-readable:
`https://forge.laravel.com/ips-v4.txt` · Port: `22` · File: [`ips/forge-v4.txt`](ips/forge-v4.txt)

```
159.203.150.232
159.203.150.216
45.55.124.124
165.227.248.218
142.93.78.212     # Forge Terminal (Laravel VPS only)
```

Optional support jumpbox: `129.212.144.126`. Forge emails customers several weeks before an IP changes.
If you also restrict HTTP, allow traffic to and from `forge.laravel.com`.

### RunCloud

Source: <https://runcloud.io/docs/whitelist-runcloud-ip-addresses> (*manual*) · Port: **`34210`** (RunCloud agent)
· File: [`ips/runcloud-v4.txt`](ips/runcloud-v4.txt)

```
52.53.52.35
54.177.105.133
54.176.244.231
52.52.156.27
54.215.67.177
54.193.194.57
50.18.61.175
54.193.36.212
```

### Cloudways

Cloudways is fully managed, so you don't run your own firewall. Use the dashboard instead:
*Servers → Security → Shell Access* (SSH/SFTP allow-list) and the *MySQL* tab for remote
DB access. To lock HTTP down to a proxy, use the provider firewall (if your Cloudways
provider supports it) or the nginx allow-only approach via support.

---

## Keeping lists up to date

```bash
python3 scripts/update_ips.py            # all fetchable providers
python3 scripts/update_ips.py cloudflare # just one
```

- Standard library only, no dependencies.
- Every entry is validated as an IP/CIDR, so a broken HTML response can't end up in a list.
- A run refuses to write a list that shrank by more than 50%, so a flaky endpoint can't lock
  out a CDN.
- [`.github/workflows/update-ips.yml`](.github/workflows/update-ips.yml) runs it daily and opens a PR
  when anything changes.

Lists marked *manual* (SpinupWP, GridPane, RunCloud, Ploi uptime) have no machine-readable
source. An agent or human refreshes them by following [`UPDATE_PROMPT.md`](UPDATE_PROMPT.md).

On your servers, pull and re-apply on a timer, for example:

```cron
17 4 * * * cd /opt/origin-lockdown && git pull -q && nft -f /etc/nftables.d/origin-lockdown.nft
```

(Review changes before auto-applying on production. A compromised list is a compromised firewall.)

## Contributing

To add a provider:

1. Add an entry to [`sources.json`](sources.json) (`kind`: `proxy` or `panel`; `method`: `fetch`
   if there's a machine-readable endpoint, otherwise `manual`).
2. Run `python3 scripts/update_ips.py <id>` or create `ips/<id>-v4.txt` / `-v6.txt` by hand.
3. Add a section to this README with the official source link, ports and quirks.

Only use **official** provider sources. Never add IPs from forum posts or third-party mirrors.

Wanted: Akamai, Imperva, Gcore, KeyCDN, Kinsta, WP Engine, xCloud, FlyWP, ServerAvatar, CloudPanel / Hestia
(if they publish anything), UptimeRobot / Better Stack monitor IPs.

## License

[MIT](LICENSE). IP data belongs to the respective providers and is mirrored from their public pages.
