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
