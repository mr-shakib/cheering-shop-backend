#!/usr/bin/env bash
# One-time VPS hardening + Docker install. Run ONCE as root on a fresh
# Hostinger KVM instance:  bash bootstrap-vps.sh <your-deploy-username>
#
# Idempotent: safe to re-run.
set -euo pipefail

DEPLOY_USER="${1:-deploy}"

echo "==> Updating packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq

echo "==> Installing base packages"
apt-get install -y -qq ca-certificates curl gnupg ufw fail2ban unattended-upgrades git

echo "==> Creating deploy user '$DEPLOY_USER' (non-root; docker group)"
if ! id -u "$DEPLOY_USER" >/dev/null 2>&1; then
    adduser --disabled-password --gecos "" "$DEPLOY_USER"
fi
usermod -aG sudo "$DEPLOY_USER"

# Copy root's authorised keys so you can log in as the deploy user immediately.
if [ -f /root/.ssh/authorized_keys ]; then
    mkdir -p "/home/$DEPLOY_USER/.ssh"
    cp /root/.ssh/authorized_keys "/home/$DEPLOY_USER/.ssh/"
    chown -R "$DEPLOY_USER:$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"
    chmod 700 "/home/$DEPLOY_USER/.ssh"
    chmod 600 "/home/$DEPLOY_USER/.ssh/authorized_keys"
fi

echo "==> Installing Docker Engine"
if ! command -v docker >/dev/null 2>&1; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin
fi
usermod -aG docker "$DEPLOY_USER"

echo "==> Firewall"
# NOTE: Docker writes its own iptables rules that BYPASS ufw. This is why the
# production compose file publishes no database ports — ufw alone would not
# protect them.
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

echo "==> Hardening SSH (key-only, no root login)"
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PubkeyAuthentication.*/PubkeyAuthentication yes/' /etc/ssh/sshd_config
systemctl restart ssh || systemctl restart sshd

echo "==> fail2ban + unattended security upgrades"
systemctl enable --now fail2ban
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> Swap (2G) — 8 GB RAM is ample, but swap prevents the OOM killer from"
echo "    reaping Postgres during a large migration or backup."
if ! swapon --show | grep -q .; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    sysctl -w vm.swappiness=10 >/dev/null
    echo 'vm.swappiness=10' >> /etc/sysctl.conf
fi

echo "==> Docker log rotation (containers otherwise fill the disk)"
cat > /etc/docker/daemon.json <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
JSON
systemctl restart docker

echo
echo "DONE."
echo "  Verify you can log in as '$DEPLOY_USER' in a SECOND terminal BEFORE"
echo "  closing this one — root login is now disabled."
