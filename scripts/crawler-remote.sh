#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<EOF
Usage: crawler-remote.sh <command> <host>

Commands:
  deploy <host>    Build, push, and deploy crawler to remote host
  doctor <host>    Remote health check
  logs <host>      Remote log tail (last 50 lines)
  config push <host>  Sync local .env to remote host

Host: root@ip-or-hostname
EOF
    exit 1
}

[ $# -lt 2 ] && usage

CMD="$1"
HOST="$2"

case "$CMD" in
    deploy)
        echo "→ Building Docker image..."
        docker build -t ghcr.io/capacium/capacium-crawler:latest .
        echo "→ Pushing Docker image..."
        docker push ghcr.io/capacium/capacium-crawler:latest
        echo "→ Deploying to $HOST..."
        ssh "$HOST" 'cd /opt/capacium/capacium-exchange && docker compose pull capacium-crawler && docker compose up -d --force-recreate capacium-crawler'
        echo "→ Deploy complete"
        ;;
    doctor)
        echo "→ Running remote health check on $HOST..."
        scp "$(dirname "$0")/server-doctor.sh" "$HOST:/tmp/server-doctor.sh"
        ssh "$HOST" 'bash /tmp/server-doctor.sh'
        ;;
    logs)
        echo "→ Crawler logs from $HOST..."
        ssh "$HOST" 'docker logs --tail 50 capacium-crawler 2>&1'
        ;;
    config)
        echo "→ Syncing config to $HOST..."
        ssh "$HOST" 'mkdir -p /opt/capacium'
        scp .env "$HOST:/opt/capacium/.env"
        echo "→ Config synced"
        ;;
    *)
        usage
        ;;
esac
