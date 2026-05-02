#!/usr/bin/env bash
# Capacium Health Observer — Agent-facing health monitoring
# Cross-references Exchange API, Crawler, Dashboard, server-doctor
# Emits structured JSON on --json for machine consumption
set -euo pipefail

JSON_MODE=false
[ "${1:-}" = "--json" ] && JSON_MODE=true

EXCHANGE_URL="${EXCHANGE_URL:-https://api.capacium.xyz}"
DASHBOARD_URL="${DASHBOARD_URL:-https://dash.capacium.xyz}"

timestamp() {
    date -u '+%Y-%m-%dT%H:%M:%SZ'
}

if $JSON_MODE; then
    STATS=$(curl -sf --max-time 10 "$EXCHANGE_URL/v2/stats" 2>/dev/null || echo '{}')
    API_OK=$(curl -so /dev/null -w "%{http_code}" --max-time 10 "$EXCHANGE_URL/v2/stats" 2>/dev/null || echo "000")
    DASH_OK=$(curl -so /dev/null -w "%{http_code}" --max-time 10 "$DASHBOARD_URL" 2>/dev/null || echo "000")
    CRAWLER_HEALTH=$(echo "$STATS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('crawler_health','unknown'))" 2>/dev/null || echo "unknown")
    LISTINGS=$(echo "$STATS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('total_listings',0))" 2>/dev/null || echo "0")
    ENRICHED=$(echo "$STATS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('enriched_count',0))" 2>/dev/null || echo "0")

    python3 -c "
import json, sys
status = {
    'timestamp': '$(timestamp)',
    'exchange_api': {'reachable': '$API_OK' == '200', 'http_code': '$API_OK'},
    'dashboard': {'reachable': '$DASH_OK' == '200', 'http_code': '$DASH_OK'},
    'crawler_health': '$CRAWLER_HEALTH',
    'listings': '$LISTINGS',
    'enriched_count': '$ENRICHED',
    'enrichment_pct': round(int('$ENRICHED') / int('$LISTINGS') * 100, 1) if int('$LISTINGS') > 0 else 0
}
print(json.dumps(status, indent=2))
" 2>/dev/null

else
    echo "========================================="
    echo "  Capacium Health Observer"
    echo "  $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo "========================================="
    echo ""

    echo "--- Exchange API ---"
    HTTP_CODE=$(curl -so /dev/null -w "%{http_code}" --max-time 10 "$EXCHANGE_URL/v2/stats" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        echo "  [✓] Exchange API reachable"
        STATS=$(curl -sf --max-time 10 "$EXCHANGE_URL/v2/stats" 2>/dev/null)
        echo "$STATS" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'  Listings:     {d.get(\"total_listings\", \"?\")}')
print(f'  Enriched:     {d.get(\"enriched_count\", \"?\")}')
print(f'  Top Stars:    {d.get(\"top_stars\", \"?\")}')
print(f'  Crawler:      {d.get(\"crawler_health\", \"?\")}')
" 2>/dev/null
    else
        echo "  [✗] Exchange API unreachable (HTTP $HTTP_CODE)"
    fi
    echo ""

    echo "--- Dashboard ---"
    DASH_CODE=$(curl -so /dev/null -w "%{http_code}" --max-time 10 "$DASHBOARD_URL" 2>/dev/null || echo "000")
    if [ "$DASH_CODE" = "200" ]; then
        echo "  [✓] Dashboard reachable"
    else
        echo "  [✗] Dashboard unreachable (HTTP $DASH_CODE)"
    fi
    echo ""

    echo "========================================="
    echo "  Health check complete"
    echo "========================================="
fi
