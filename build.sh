#!/bin/sh
# Builds index.html = PWA head (src/head.html) + page body (src/app.html).
set -e
cd "$(dirname "$0")"
{ cat src/head.html; cat src/app.html; echo '</body></html>'; } > index.html.tmp
mv index.html.tmp index.html
