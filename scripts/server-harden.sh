#!/usr/bin/env bash
set -euo pipefail
# Idempotent server hardening for Capacium CX33
# Run as root: bash server-harden.sh
# Dry run: bash server-harden.sh --dry-run

DRY_RUN=false
[ "${1:-}" = "--dry-run" ] && DRY_RUN=true && echo "DRY RUN MODE"

_run() {
    if $DRY_RUN; then
        echo "[DRY] $*"
    else
        echo "→ $*"
        eval "$@"
    fi
}

echo "=== Capacium Server Hardening ==="
echo ""

# 1. SSH hardening
echo "--- SSH Hardening ---"
_run "sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config"
_run "sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config"
_run "sed -i 's/^#*PubkeyAuthentication.*/PubkeyAuthentication yes/' /etc/ssh/sshd_config"
echo ""

# 2. UFW
echo "--- UFW Firewall ---"
_run "apt-get update -qq && apt-get install -y -qq ufw"
_run "ufw --force reset"
_run "ufw default deny incoming"
_run "ufw default allow outgoing"
_run "ufw allow 22/tcp comment 'SSH'"
_run "ufw allow 80/tcp comment 'HTTP'"
_run "ufw allow 443/tcp comment 'HTTPS'"
_run "ufw --force enable"
echo ""

# 3. Fail2ban
echo "--- Fail2Ban ---"
_run "apt-get install -y -qq fail2ban"
cat > /tmp/jail.local << 'EOF'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5
ignoreip = 127.0.0.1/8

[sshd]
enabled = true
port = ssh
logpath = %(sshd_log)s

[caddy-http]
enabled = true
port = http,https
filter = caddy
logpath = /var/log/caddy/access.log
maxretry = 10
EOF
_run "cp /tmp/jail.local /etc/fail2ban/jail.local"
_run "systemctl enable fail2ban"
_run "systemctl restart fail2ban"
echo ""

# 4. Unattended upgrades
echo "--- Unattended Upgrades ---"
_run "apt-get install -y -qq unattended-upgrades apt-listchanges"
_run "sed -i 's|//\"\${distro_id}:\${distro_codename}-security\";|\"\${distro_id}:\${distro_codename}-security\";|' /etc/apt/apt.conf.d/50unattended-upgrades"
_run "systemctl enable unattended-upgrades"
echo ""

# 5. ClamAV
echo "--- ClamAV ---"
_run "apt-get install -y -qq clamav clamav-daemon"
_run "systemctl enable clamav-daemon 2>/dev/null || pkill clamd && freshclam && clamd &"
echo ""

echo "=== Hardening complete ==="
