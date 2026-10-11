#!/bin/sh
# Builds index.html = PWA head (_head.html) + shared page body (also published as a claude.ai artifact).
set -e
cd "$(dirname "$0")"
BODY="${1:-/home/user/dartkollen/index.html}"
{ cat _head.html; cat "$BODY"; echo '</body></html>'; } > index.html.tmp
mv index.html.tmp index.html
