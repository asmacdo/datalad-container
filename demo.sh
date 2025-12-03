#!/bin/bash
# demo.sh - Demonstrate datalad-container images/profiles refactor
#
# Usage: ./demo.sh [base_dir]
#        base_dir defaults to /tmp

set -e

BASE_DIR="${1:-/tmp}"
DEMO_DIR="$BASE_DIR/datalad-container-demo-$$"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

section() {
    echo ""
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
    echo ""
}

info() {
    echo -e "${GREEN}► $1${NC}"
}

warn() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

run_cmd() {
    echo -e "${YELLOW}\$ $1${NC}"
    eval "$1"
}

show_last_commit() {
    echo ""
    info "Last commit:"
    git --no-pager log -1 --oneline
    echo ""
}

# ============================================================================
section "SETUP: Create demo dataset"
# ============================================================================

info "Creating demo directory: $DEMO_DIR"
mkdir -p "$DEMO_DIR"
cd "$DEMO_DIR"

run_cmd "datalad create ."

info "Adding alpine image..."
run_cmd "datalad containers-add alpine:latest --url docker://alpine:latest"

# ============================================================================
section "PHASE 1: containers-add + datalad run (raw docker command)"
# ============================================================================

info "Using datalad run with explicit docker command (no containers-run)"
run_cmd "datalad run --input .datalad/containers/images/alpine/latest/image --output phase1-output.txt -- docker run --rm datalad-container/alpine:latest sh -c 'echo Phase 1: raw datalad run > /dev/stdout'"

# Create output manually since docker stdout doesn't redirect to file easily
echo "Phase 1: raw datalad run" > phase1-output.txt
git add phase1-output.txt && git commit --amend --no-edit

show_last_commit

# ============================================================================
section "PHASE 2: containers-run --image --exec"
# ============================================================================

info "Using containers-run with explicit --image and --exec flags"
run_cmd "datalad containers-run --image alpine:latest --exec 'docker run --rm --user \$(id -u):\$(id -g) -v \$(pwd):/work -w /work {img} {cmd}' --output phase2-output.txt --expand outputs -- sh -c 'echo Phase 2: containers-run with --image --exec > {outputs}'"

show_last_commit

# ============================================================================
section "PHASE 3a: Create profile with image, containers-run --profile"
# ============================================================================

info "Creating profiles directory and docker-alpine profile..."
mkdir -p .datalad/containers/profiles

cat > .datalad/containers/profiles/docker-alpine.yaml << 'EOF'
image: alpine:latest
exec: docker run --rm --user $(id -u):$(id -g) -v $(pwd):/work -w /work {img} {cmd}
EOF

info "Profile contents:"
cat .datalad/containers/profiles/docker-alpine.yaml

info "Saving profile to dataset..."
run_cmd "datalad save -m 'Add docker-alpine profile' .datalad/containers/profiles/"

run_cmd "datalad containers-run --profile docker-alpine --output phase3a-output.txt --expand outputs -- sh -c 'echo Phase 3a: profile with image > {outputs}'"

show_last_commit

# ============================================================================
section "PHASE 3b: containers-list and containers-profiles output"
# ============================================================================

info "Listing containers:"
run_cmd "datalad containers-list"

echo ""
info "Listing profiles:"
run_cmd "datalad containers-profiles"

# ============================================================================
section "PHASE 3c: Profile with extends (inheritance)"
# ============================================================================

info "Creating docker-alpine-env profile that extends docker-alpine..."
cat > .datalad/containers/profiles/docker-alpine-env.yaml << 'EOF'
extends: docker-alpine
exec: docker run --rm --user $(id -u):$(id -g) -v $(pwd):/work -w /work -e MY_VAR=hello-from-extended-profile {img} {cmd}
EOF

info "Profile contents:"
cat .datalad/containers/profiles/docker-alpine-env.yaml

run_cmd "datalad save -m 'Add docker-alpine-env profile' .datalad/containers/profiles/"

run_cmd "datalad containers-run --profile docker-alpine-env --output phase3c-output.txt --expand outputs -- sh -c 'echo Phase 3c: MY_VAR=\$MY_VAR > {outputs}'"

info "Output file contents:"
cat phase3c-output.txt

show_last_commit

# ============================================================================
section "PHASE 3d: CLI override --exec"
# ============================================================================

info "Using --profile but overriding --exec to add environment variable..."
run_cmd "datalad containers-run --profile docker-alpine --exec 'docker run --rm --user \$(id -u):\$(id -g) -v \$(pwd):/work -w /work -e CLI_OVERRIDE=yes {img} {cmd}' --output phase3d-output.txt --expand outputs -- sh -c 'echo Phase 3d: CLI_OVERRIDE=\$CLI_OVERRIDE > {outputs}'"

info "Output file contents:"
cat phase3d-output.txt

show_last_commit

# ============================================================================
section "PHASE 3e: CLI override --image"
# ============================================================================

info "Adding busybox image..."
run_cmd "datalad containers-add busybox:latest --url docker://busybox:latest"

info "Using docker-alpine profile but overriding --image to use busybox..."
run_cmd "datalad containers-run --profile docker-alpine --image busybox:latest --output phase3e-output.txt --expand outputs -- sh -c 'echo Phase 3e: running busybox instead of alpine > {outputs}'"

info "Output file contents:"
cat phase3e-output.txt

show_last_commit

# ============================================================================
section "PHASE 3f: Error case - missing image (early validation)"
# ============================================================================

info "Creating profile that references non-existent image..."
cat > .datalad/containers/profiles/bad-profile.yaml << 'EOF'
image: nonexistent:v999
exec: docker run --rm {img} {cmd}
EOF

run_cmd "datalad save -m 'Add bad-profile for testing' .datalad/containers/profiles/"

info "Attempting to use bad-profile (should fail early)..."
echo ""
if datalad containers-run --profile bad-profile -- echo "this should not run" 2>&1; then
    warn "ERROR: Command should have failed!"
else
    info "Command failed as expected (early validation works)"
fi

# Clean up bad profile
rm .datalad/containers/profiles/bad-profile.yaml
run_cmd "datalad save -m 'Remove bad-profile' .datalad/containers/profiles/"

# ============================================================================
section "PHASE 3g: Base profiles without image (require --image flag)"
# ============================================================================

info "Creating base profiles for different runtimes (no image specified)..."

cat > .datalad/containers/profiles/docker-default.yaml << 'EOF'
exec: docker run --rm --user $(id -u):$(id -g) -v $(pwd):/work -w /work {img} {cmd}
EOF

cat > .datalad/containers/profiles/apptainer-default.yaml << 'EOF'
exec: apptainer exec oci:{img_path} {cmd}
EOF

cat > .datalad/containers/profiles/podman-default.yaml << 'EOF'
exec: podman run --rm --userns=keep-id -v $(pwd):/work:Z -w /work {img} {cmd}
EOF

run_cmd "datalad save -m 'Add base runtime profiles' .datalad/containers/profiles/"

info "Listing all profiles:"
run_cmd "datalad containers-profiles"

# Test docker-default (should work)
info "Testing docker-default profile with --image alpine:latest..."
run_cmd "datalad containers-run --profile docker-default --image alpine:latest --output phase3g-docker.txt --expand outputs -- sh -c 'echo Phase 3g: docker-default profile > {outputs}'"
show_last_commit

# Test apptainer-default if available
if command -v apptainer &> /dev/null || command -v singularity &> /dev/null; then
    info "Testing apptainer-default profile..."
    run_cmd "datalad containers-run --profile apptainer-default --image alpine:latest --output phase3g-apptainer.txt --expand outputs -- sh -c 'echo Phase 3g: apptainer-default profile > {outputs}'"
    show_last_commit
else
    warn "Skipping apptainer test (apptainer/singularity not installed)"
fi

# Test podman-default if available
if command -v podman &> /dev/null; then
    info "Testing podman-default profile..."
    run_cmd "datalad containers-run --profile podman-default --image alpine:latest --output phase3g-podman.txt --expand outputs -- sh -c 'echo Phase 3g: podman-default profile > {outputs}'"
    show_last_commit
else
    warn "Skipping podman test (podman not installed)"
fi

# ============================================================================
section "DEMO COMPLETE"
# ============================================================================

info "Demo directory: $DEMO_DIR"
echo ""
info "Final git log:"
git --no-pager log --oneline

echo ""
info "All containers:"
datalad containers-list

echo ""
info "All profiles:"
datalad containers-profiles

echo ""
echo -e "${GREEN}Demo completed successfully!${NC}"
