#!/usr/bin/env bash
set -euo pipefail

echo "========================================="
echo "  Capacium Server Health Report"
echo "  $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "========================================="
echo ""

# 1. Docker containers
echo "--- Docker Containers ---"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "  [WARN] Docker not running"
echo ""

# 2. Disk usage
echo "--- Disk Usage ---"
df -h / | awk 'NR==2{printf "  Root: %s used (%s/%s)\n", $5, $3, $2}'
echo ""
# Check if > 80%
DISK_USE=$(df / | awk 'NR==2{print $5}' | sed 's/%//')
if [ "$DISK_USE" -gt 80 ]; then
    echo "  [WARN] Disk usage at ${DISK_USE}%"
fi
echo ""

# 3. Memory
echo "--- Memory ---"
free -h | awk '/Mem/{printf "  RAM:    %s used / %s total\n", $3, $2}'
free -h | awk '/Swap/{printf "  Swap:   %s used / %s total\n", $3, $2}'
echo ""

# 4. Load
echo "--- Load ---"
uptime | awk -F'load average: ' '{printf "  Load:   %s\n", $2}'
echo ""

# 5. SSL Certificate
echo "--- SSL Certificate ---"
CERT_END=$(echo | openssl s_client -connect api.capacium.xyz:443 -servername api.capacium.xyz 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
if [ -n "$CERT_END" ]; then
    echo "  api.capacium.xyz expires: $CERT_END"
    CERT_SECONDS=$(date -j -f "%b %d %T %Y %Z" "$CERT_END" +%s 2>/dev/null || echo 0)
    NOW=$(date +%s)
    if [ "$CERT_SECONDS" -gt 0 ]; then
        DAYS_LEFT=$(( (CERT_SECONDS - NOW) / 86400 ))
        if [ "$DAYS_LEFT" -lt 30 ]; then
            echo "  [WARN] Certificate expires in $DAYS_LEFT days"
        else
            echo "  [OK] $DAYS_LEFT days remaining"
        fi
    fi
else
    echo "  [FAIL] Could not retrieve certificate"
fi
echo ""

# 6. Exchange API
echo "--- Exchange API ---"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 https://api.capacium.xyz/v2/stats 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    echo "  [OK] Exchange API reachable (HTTP $HTTP_CODE)"
    STATS=$(curl -s --max-time 10 https://api.capacium.xyz/v2/stats 2>/dev/null)
    LISTINGS=$(echo "$STATS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('total_listings','?'))" 2>/dev/null || echo "?")
    echo "  Listings: $LISTINGS"
else
    echo "  [FAIL] Exchange API returned HTTP $HTTP_CODE"
fi
echo ""

# 7. Uptime
echo "--- System Uptime ---"
uptime -p 2>/dev/null || uptime
echo ""

echo "========================================="
echo "  Health check complete"
echo "========================================="
