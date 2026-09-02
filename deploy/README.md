# Production hardening

These files implement the server-side parts of the public-service hardening:

- Streamlit listens only on `127.0.0.1:8501`; port 8501 must not be reachable from the internet.
- The service runs as the unprivileged `tmallcomment` account with a read-only application tree and explicit writable directories.
- Nginx limits request/connection rates and upload size before traffic reaches Streamlit.

The commands below assume the historical deployment paths `/opt/tmall-comment` and `.venv311`. Inspect the current unit and Nginx configuration before replacing anything.

## Install the service

Run on the server as an administrator after the repository revision containing this directory has been deployed:

```bash
id -u tmallcomment >/dev/null 2>&1 || sudo useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin --user-group tmallcomment
sudo install -d -m 0750 -o root -g tmallcomment /etc/tmall-comment
sudo install -m 0640 -o root -g tmallcomment /opt/tmall-comment/deploy/systemd/tmall-comment.service /etc/systemd/system/tmall-comment.service
sudo install -d -m 0750 -o tmallcomment -g tmallcomment /opt/tmall-comment/projects /opt/tmall-comment/output
sudo chown -R tmallcomment:tmallcomment /opt/tmall-comment/projects /opt/tmall-comment/output
sudo systemctl daemon-reload
sudo systemctl enable --now tmall-comment.service
sudo systemctl status tmall-comment.service --no-pager
```

If project workbooks are later copied as `root`, restore the service ownership and
minimum permissions before restarting either application. One unreadable workbook
prevents the WeChat estimate catalog from being built:

```bash
sudo chown tmallcomment:tmallcomment /opt/tmall-comment/projects
sudo chmod 0750 /opt/tmall-comment/projects
sudo find /opt/tmall-comment/projects -maxdepth 1 -type f -name '*.xlsx' -exec chown tmallcomment:tmallcomment {} + -exec chmod 0640 {} +
cd /tmp && sudo -u tmallcomment find /opt/tmall-comment/projects -maxdepth 1 -type f -name '*.xlsx' ! -readable -print
```

The last command must produce no workbook paths.

Create `/etc/tmall-comment/tmall-comment.env` with mode `0640`, owned by `root:tmallcomment`. Put secrets there or point `DEEPSEEK_API_KEY_FILE` at a root-owned, group-readable key file outside the checkout. Example non-secret limits:

```ini
TMC_MAX_UPLOAD_FILES=10
TMC_MAX_UPLOAD_FILE_MB=20
TMC_MAX_UPLOAD_TOTAL_MB=50
TMC_MAX_ZIP_EXPANDED_MB=80
TMC_MAX_CSV_ROWS=50000
TMC_MAX_UPDATE_RUNS_PER_HOUR=6
TMC_MIN_SECONDS_BETWEEN_UPDATES=30
```

Do not put API keys into the unit file or Git repository.

## Nginx and firewall

Copy `nginx/tmall-comment-rate-limits.conf` into `/etc/nginx/conf.d/`. Add the contents of `nginx/tmall-comment-location.conf` inside the server block that currently serves `/TmallComment/`; do not add a second `server {}` block for the same IP/port.

Before reload, validate the complete Nginx configuration:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

For UFW, the intended exposure is only SSH from approved IPs plus Nginx on 80/443. Never expose port 8501:

```bash
sudo ufw deny 8501/tcp
sudo ufw status numbered
```

If the provider has a cloud security group, remove its inbound `8501/tcp` rule there too. Verify from a machine outside the server network that `http://SERVER_IP:8501/` cannot connect, while `http://SERVER_IP/TmallComment/_stcore/health` returns `ok`.

`tmall-comment.service` starts with `--server.maxUploadSize=20`; the application additionally limits total upload size, archive expansion, CSV rows, update frequency, and concurrent updates.

## WeChat callback service

The WeChat callback is a separate FastAPI/Uvicorn process on
`127.0.0.1:8511`. It does not change the Streamlit process or its
`/TmallComment/` route.

1. Create the isolated `/opt/tmall-comment/.venv-wechat` environment and
   install `requirements-wechat.txt` into it. This keeps callback dependencies
   out of the Streamlit environment.
2. Create `/etc/tmall-comment/wechat-sales.env` with mode `0640`, owned by
   `root:tmallcomment`, and set `WECHAT_TOKEN`. For safe mode, also set the
   official account's `WECHAT_APP_ID` and `WECHAT_ENCODING_AES_KEY`. AppSecret
   is not needed. Set `ECCOMMENT_ESTIMATE_URL` to the built-in loopback endpoint
   `http://127.0.0.1:8511/api/sales/estimate`, set `ECCOMMENT_PROJECTS_DIR` to
   `/opt/tmall-comment/projects`, and generate one private service token with
   `openssl rand -hex 32` for `ECCOMMENT_ESTIMATE_TOKEN`. The caller and endpoint
   use the same environment value; it is not a WeChat or model-provider token.
   Never put real credentials in the repository or unit file.
3. Install `deploy/systemd/wechat-sales.service` as
   `/etc/systemd/system/wechat-sales.service`.
4. Include `deploy/nginx/wechat-sales-location.conf` inside the existing HTTPS
   `server {}` block. Do not replace that block or the `/TmallComment/`
   locations.
5. Validate and restart only the new service and Nginx configuration:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now wechat-sales.service
sudo systemctl restart wechat-sales.service
sudo nginx -t
sudo systemctl reload nginx
```

Local health check: `curl http://127.0.0.1:8511/health`. For a signed GET test,
generate the signature outside shell history or logs and send
`signature`, `timestamp`, `nonce`, and `echostr` as query parameters. Invalid
signatures must return `403`; POST currently logs request metadata and returns
the standard passive-reply XML for a signed official-account text message. A
plaintext callback uses `signature`; a safe-mode callback uses
`encrypt_type=aes`, `msg_signature`, and an XML `Encrypt` envelope. In both
modes, text containing `e.tb.cn`, `item.taobao.com`, or `detail.tmall.com` is
sent to the configured ECComment endpoint and formatted into a WeChat reply.
Other text replies with `请发送淘宝商品链接`; ECComment failures reply with
`查询失败，请稍后重试`. Non-text messages return `200 success`. The synchronous
callback does not use AI, a database, a user system, or WeCom. Keep the
ECComment timeout below WeChat's passive-reply deadline.

The built-in `POST /api/sales/estimate` endpoint is intentionally not included
in Nginx. The callback reaches it over loopback, authenticated with the bearer
token above. It reads top-level project workbooks without modifying them, uses
the existing 5% review-rate calculation, and returns the most recent month that
has dated primary reviews. The workbook catalog is warmed during service startup
so the first WeChat query does not pay Excel loading time. Restart
`wechat-sales.service` after dependencies or environment values change.
