#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"

# If this .command file is copied into the repo, use that repo.
# Otherwise user can also place it in the project root and double-click.
PROJECT_DIR="$(pwd)"

echo "=== Safe GitHub First Push ==="
echo "Project: $PROJECT_DIR"
echo

if [[ ! -d ".git" ]]; then
  git init
fi

cat > .gitignore <<'EOF'
# secrets
.env
.env.*
!.env.example
*.pem
*.key
*.p12
*.pfx
*.crt
*.cer
*.mobileprovision
secrets.*
config.local.*
*.secret

# local db / state
*.sqlite
*.sqlite3
*.db

# logs
*.log
logs/
npm-debug.log*
yarn-debug.log*
yarn-error.log*
pnpm-debug.log*

# Python
__pycache__/
*.py[cod]
.venv/
venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/

# Node
node_modules/
dist/
build/
.next/
coverage/

# macOS
.DS_Store

# IDE
.vscode/
.idea/

# temp/cache
tmp/
temp/
.cache/
EOF

# Untrack common sensitive/generated files if already tracked
for target in .env .env.local .env.development .env.production; do
  git rm --cached "$target" >/dev/null 2>&1 || true
done

for target in .venv venv __pycache__ node_modules dist build .next; do
  git rm -r --cached "$target" >/dev/null 2>&1 || true
done

# Stage everything safe
git add .

echo
echo "=== Files staged for commit ==="
git diff --cached --name-only | sed 's/^/ - /'
echo

echo "=== Dangerous patterns check ==="
BAD="$(git diff --cached --name-only | grep -Ei '(^|/)\.env($|\.)|\.pem$|\.key$|\.p12$|\.pfx$|\.sqlite3?$|\.db$' || true)"
if [[ -n "$BAD" ]]; then
  echo "STOP: suspicious files are still staged:"
  echo "$BAD"
  echo
  echo "Remove them first, then run again."
  read -k 1 "?Press any key to close..."
  exit 1
fi

if git diff --cached --quiet; then
  echo "Nothing to commit."
else
  git commit -m "Initial safe commit" || true
fi

echo
echo "Paste GitHub repo URL, for example:"
echo "https://github.com/USERNAME/REPO.git"
read "REMOTE_URL?GitHub repo URL: "

if [[ -z "${REMOTE_URL// }" ]]; then
  echo "No URL entered. Commit is done locally only."
  read -k 1 "?Press any key to close..."
  exit 0
fi

if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE_URL"
else
  git remote add origin "$REMOTE_URL"
fi

git branch -M main
git push -u origin main

echo
echo "Done. Safe push completed."
read -k 1 "?Press any key to close..."
