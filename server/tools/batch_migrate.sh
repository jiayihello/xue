#!/bin/bash
set -euo pipefail

# --- Configuration ---
# Target server SSH details
TARGET_SSH_HOST="root@45.89.99.183"
TARGET_SSH_PASS="liukai.00"

# Path to the server directory on both source and target machines
# 自动检测当前脚本所在目录
SERVER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# --- End of Configuration ---

# Ensure we are in the correct directory
cd "$SERVER_DIR" || { echo "Error: Directory $SERVER_DIR not found."; exit 1; }

# Ensure required tools on source
need_pkgs=()
command -v jq >/dev/null 2>&1 || need_pkgs+=(jq)
command -v sshpass >/dev/null 2>&1 || need_pkgs+=(sshpass)
if [ ${#need_pkgs[@]} -gt 0 ]; then
  if command -v apt >/dev/null 2>&1; then
    echo "Installing missing packages: ${need_pkgs[*]} ..."
    apt update -y && apt install -y "${need_pkgs[@]}"
  else
    echo "Please install required packages first: ${need_pkgs[*]}"; exit 1
  fi
fi

# Ensure target has server dir and required files
echo "Ensuring target server environment ..."
sshpass -p "$TARGET_SSH_PASS" ssh -o StrictHostKeyChecking=no "$TARGET_SSH_HOST" "mkdir -p $SERVER_DIR"
if ! sshpass -p "$TARGET_SSH_PASS" ssh -o StrictHostKeyChecking=no "$TARGET_SSH_HOST" "[ -f $SERVER_DIR/lxc_manager.py ] && [ -f $SERVER_DIR/flow_manager.py ] && [ -f $SERVER_DIR/migrate_containers.py ]"; then
  echo "Syncing server code to target ..."
  sshpass -p "$TARGET_SSH_PASS" scp -o StrictHostKeyChecking=no -r "$SERVER_DIR/"* "${TARGET_SSH_HOST}:${SERVER_DIR}/"
fi

# Always update migrate_containers.py to latest on target
sshpass -p "$TARGET_SSH_PASS" scp -o StrictHostKeyChecking=no "$SERVER_DIR/migrate_containers.py" "${TARGET_SSH_HOST}:${SERVER_DIR}/" 1>/dev/null 2>&1 || true

# Select only containers with limits.memory = 512M/MB/MiB
echo "Selecting containers with limits.memory = 512M ..."
CONTAINERS=$(lxc list --format=json | jq -r '.[] | select(.config["limits.memory"] | test("(?i)^\\s*512\\s*(M|MB|MiB)\\s*$")) | .name')

if [ -z "$CONTAINERS" ]; then
    echo "No 512M containers found to migrate."
    exit 0
fi

echo "Found containers to migrate:"
echo "$CONTAINERS"
echo "----------------------------------------"
read -p "Press Enter to start migrating these containers, or Ctrl+C to cancel."

# Loop through each selected container and migrate it
for container in $CONTAINERS; do
    echo "======================================="
    echo "Migrating container: $container"
    echo "======================================="

    # 1. Export the container on the source machine
    echo "--> Step 1/4: Exporting '$container' on source machine ..."
    if ! python3 migrate_containers.py export "$container"; then
        echo "❌ Error: Failed to export '$container'. Skipping to next container."
        continue
    fi

    PACKAGE_NAME="${container}_migration_package.tar.gz"
    if [ ! -f "$PACKAGE_NAME" ]; then
        echo "❌ Error: Migration package '$PACKAGE_NAME' not found after export. Skipping."
        continue
    fi

    # 2. Transfer the package to the target machine
    echo "--> Step 2/4: Transferring '$PACKAGE_NAME' to $TARGET_SSH_HOST ..."
    if ! sshpass -p "$TARGET_SSH_PASS" scp -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -o ServerAliveCountMax=120 "$PACKAGE_NAME" "${TARGET_SSH_HOST}:${SERVER_DIR}/"; then
        echo "❌ Error: Failed to transfer package for '$container'. Keeping local package for inspection."
        continue
    fi

    # 3. Import the container on the target machine via SSH
    echo "--> Step 3/4: Importing '$container' on target machine ..."
    if sshpass -p "$TARGET_SSH_PASS" ssh -t -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -o ServerAliveCountMax=120 \
        "$TARGET_SSH_HOST" "cd ${SERVER_DIR} && PYTHONUNBUFFERED=1 python3 -u migrate_containers.py import '${PACKAGE_NAME}'"; then
        # 4. Clean up the package on the source machine
        echo "--> Step 4/4: Import successful. Cleaning up source package '$PACKAGE_NAME' ..."
        rm -f "$PACKAGE_NAME"
        echo "✅ Migration of '$container' completed successfully."
    else
        echo "❌ Error: Import failed on target machine for '$container'. The package '$PACKAGE_NAME' is kept on both machines for inspection."
    fi

    echo "----------------------------------------"
    sleep 2 # Small delay before the next one
done

echo "All selected containers have been processed."

