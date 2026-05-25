# Native Compute Node Deployment

Use this when you SSH into an Ubuntu compute-node instance and the management node maps one external port to a port on this instance.

The native deployment uses:

- the FastAPI backend on `127.0.0.1:8001`
- system Nginx on compute-node port `18080`
- frontend static files from `frontend/dist`
- same-origin browser API calls through `/api`

```text
management node port
  -> compute node :18080
  -> nginx
       /      -> /data/projects/llm-council/frontend/dist
       /api/* -> 127.0.0.1:8001
```

## Configure

```bash
cp .env.example .env
```

Edit `.env` for deployment ports:

```bash
BACKEND_HOST=127.0.0.1
BACKEND_PORT=8001
APP_PORT=18080
```

The LLM provider base URL and API key can be configured from the frontend settings UI after the app starts. `OPENAI_API_KEY` and `OPENAI_API_BASE_URL` in `.env` are only optional startup defaults.

The install script reads `APP_PORT`, `BACKEND_HOST`, and `BACKEND_PORT` from `.env` and writes the generated Nginx site to `/etc/nginx/sites-available/llm-council.conf`.

## Proxy Behavior

`uv sync` and the backend process inherit proxy variables from `.env` or the shell:

```bash
HTTP_PROXY=http://proxy.example:port
HTTPS_PROXY=http://proxy.example:port
NO_PROXY=localhost,127.0.0.1
```

For backend LLM/network requests:

```bash
BACKEND_USE_PROXY=1  # default: backend inherits HTTP_PROXY/HTTPS_PROXY
BACKEND_USE_PROXY=0  # unset proxy variables for the backend process
```

`npm ci` and `npm run build` intentionally unset proxy variables by default, because this compute environment previously hung when npm used the cluster proxy. To force npm to use the configured proxy, set:

```bash
NPM_USE_PROXY=1
```

To check the active shell proxy before running the installer:

```bash
env | grep -i proxy
npm config get proxy
npm config get https-proxy
```

## Install

Install system prerequisites if needed:

```bash
sudo apt-get update
sudo apt-get install -y nginx
```

Then run:

```bash
bash deploy/native/install.sh
```

The script installs Python dependencies with `uv sync`, installs frontend dependencies with npm while unsetting proxy variables, builds the frontend, installs the Nginx site, and starts or restarts the backend service.

If the instance was not booted with systemd as PID 1, the script starts the backend as a normal background process instead:

```text
.run/llm-council-backend.pid
logs/backend.log
```

This is similar to the local `start.sh` flow, but it uses the production frontend build plus Nginx instead of the Vite dev server.

## Check

```bash
bash deploy/native/status.sh
curl http://localhost:18080/
curl http://localhost:18080/api/conversations
```

To stop the backend:

```bash
bash deploy/native/stop-backend.sh
```

That stops the API backend, whether it is running as a systemd service or as a non-systemd background process. Nginx still listens on `APP_PORT` and serves the frontend, so `/api` will return 502 until the backend starts again. To stop the whole app entrypoint and free `APP_PORT`:

```bash
bash deploy/native/stop.sh
```

Then configure the management node to map its exposed port to this compute-node port:

```text
http://<management-node-ip>:<mapped-port>/
```
