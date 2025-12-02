# Proposal: Image and Container Refactor

## Overview

This proposal addresses architectural issues in datalad-container by:
1. Adopting a clean registry URL scheme
2. Storing images in their native format with provenance
3. Introducing execution profiles to separate image artifacts from runtime configuration

---

## 1. Registry URL Scheme

### Current Problem

Multiple URL schemes with inconsistent semantics:
```bash
docker://...        # Singularity pulls directly
dhub://...          # Python adapter saves as tar
oci:docker://...    # Skopeo saves as OCI directory
shub://...          # Singularity Hub
```

The scheme conflates: source registry, storage format, and execution method.

### Proposed Solution

**Protocol indicates registry source only:**

```bash
docker://org/repo:tag           # Docker Hub (docker.io)
quay://org/repo:tag             # Quay.io
ghcr://org/repo:tag             # GitHub Container Registry
shub://org/repo:tag             # Singularity Hub (legacy)
```

**Implementation:**

(TODO how do custom/local registries)

```python
REGISTRY_MAP = {
    'docker': 'docker.io',
    'quay': 'quay.io',
    'ghcr': 'ghcr.io',
    'ecr': 'public.ecr.aws',
    # extensible...
}

def resolve_registry(url):
    """docker://nipreps/mriqc:23.1.0 → docker.io/nipreps/mriqc:23.1.0"""
    protocol, path = url.split('://', 1)
    registry = REGISTRY_MAP.get(protocol)
    if registry:
        return f"{registry}/{path}"
    raise ValueError(f"Unknown registry protocol: {protocol}")
```

**Usage:**

```bash
datalad containers-add mriqc --url docker://nipreps/mriqc:23.1.0
datalad containers-add samtools --url quay://biocontainers/samtools:1.9
```

---

## 2. Native Format Storage with Provenance

### Current Problem

Storage format is determined by URL scheme, not source format:
- `docker://` → Singularity image (converted)
- `dhub://` → Docker tar (via docker save)
- `oci:docker://` → OCI directory (via skopeo)

This loses information, creates unnecessary conversions, and is confusing.

### Proposed Solution

**Store images in the format they come from the registry:**

| Registry Type | Native Format | Storage |
|---------------|---------------|---------|
| Docker/OCI registries | OCI layers | OCI directory structure |
| Singularity Hub | SIF/simg | Single file |
| Local SIF file | SIF | Copy as-is |

**Provenance tracking:**

```ini
# .datalad/config
[datalad "containers.mriqc"]
    image = .datalad/environments/mriqc/image
    source-url = docker://nipreps/mriqc:23.1.0
    source-registry = docker.io
    source-digest = sha256:abc123...
    format = oci
    fetched = 2024-01-15T10:30:00Z
```

**Git-annex integration:**

For OCI images, individual layers get registry URLs for efficient retrieval:
```bash
git annex whereis .datalad/environments/mriqc/image/blobs/sha256/abc123
# → docker.io/nipreps/mriqc@sha256:abc123
```

---

## 3. Execution Profiles

### Current Problem

Execution configuration is either:
- Hardcoded in Python (`docker_run()` with fixed flags)
   - Problem becomes worse with other runtimes, ie `podman_run()`
- Baked into cmdexec at add-time (inflexible)
    - can be changed, but requires knowledge of datalad-containers internals
- Hidden from provenance (shim invocation recorded, not actual command)

Scientists need to run the same image with different configurations:
- GPU vs CPU
- Different volume mounts
- Different runtimes (apptainer on HPC, podman on laptop)

### Proposed Solution

**Execution profiles** are named, reusable execution configurations stored alongside images or in dataset config.

#### Profile Definition

```ini
# .datalad/config

# Global profiles (apply to any image)
[datalad "execution-profile.apptainer-default"]
    runtime = apptainer
    template = apptainer exec {runtime-args} {img} {cmd}
    runtime-args = --cleanenv

[datalad "execution-profile.apptainer-gpu"]
    runtime = apptainer
    template = apptainer exec {runtime-args} {img} {cmd}
    runtime-args = --cleanenv --nv

[datalad "execution-profile.podman-default"]
    runtime = podman
    template = podman run {runtime-args} {img} {cmd}
    runtime-args = --rm --userns=keep-id -v {pwd}:/work -w /work

[datalad "execution-profile.podman-gpu"]
    runtime = podman
    template = podman run {runtime-args} {img} {cmd}
    runtime-args = --rm --userns=keep-id --device nvidia.com/gpu=all -v {pwd}:/work -w /work

# Container-specific profile
[datalad "containers.mriqc.profile.hpc"]
    extends = apptainer-gpu
    runtime-args = --cleanenv --nv --bind /scratch:/scratch
```

#### Profile Usage

```bash
# Use a named profile
datalad containers-run -n mriqc --profile apptainer-gpu mriqc --version

# Use container-specific profile
datalad containers-run -n mriqc --profile mriqc.hpc mriqc --version

# Override profile at runtime
datalad containers-run -n mriqc --profile apptainer-gpu \
    --runtime-args "--bind /data:/data" \
    mriqc /data /outputs participant

# Direct cmdexec (bypass profiles entirely)
datalad containers-run -n mriqc \
    --cmdexec "singularity exec --nv {img} {cmd}" \
    mriqc --version
```

#### Profile Resolution

Precedence (highest to lowest):
1. `--cmdexec` flag (complete override)
2. `--runtime-args` flag (extends profile)
3. `--profile` flag (named profile)
4. Container default profile (`datalad.containers.<name>.default-profile`)
5. Dataset default profile (`datalad.execution.default-profile`)
6. Built-in fallback (error if no profile found)

#### Provenance

Run records capture the **expanded** command, not profile references:

```json
{
  "cmd": "apptainer exec --cleanenv --nv --bind /scratch:/scratch oci:.datalad/environments/mriqc/image mriqc /data /outputs participant",
  "inputs": [".datalad/environments/mriqc/image", "/data"],
  "outputs": ["/outputs"],
  "container": "mriqc",
  "profile": "mriqc.hpc"
}
```

The actual execution command is always visible and reproducible.

---

## 4. Image Format Handling

### OCI Images (from Docker/Quay/GHCR registries)

```bash
datalad containers-add mriqc --url docker://nipreps/mriqc:23.1.0
```

Storage:
```
.datalad/environments/mriqc/
├── image/                    # OCI directory
│   ├── blobs/sha256/...     # Layers (git-annex tracked)
│   ├── index.json
│   └── oci-layout
└── metadata.json            # Provenance info
```

Execution profiles handle runtime differences:
- Apptainer: `apptainer exec oci:{img} {cmd}`
- Podman: loads to daemon, runs with image ID
- Docker: loads to daemon, runs with image ID

### Singularity Images (from Singularity Hub or local)

```bash
datalad containers-add dcm2niix --url shub://neurodebian/dcm2niix:latest
datalad containers-add custom --url /path/to/custom.sif
```

Storage:
```
.datalad/environments/dcm2niix/
├── image.sif                # Single file (git-annex tracked)
└── metadata.json
```

Execution is straightforward:
- Apptainer/Singularity: `apptainer exec {img} {cmd}`

### Format Conversion

Optional conversion for optimization:

```bash
# Convert OCI to SIF (for HPC performance)
datalad containers-convert mriqc --to sif

# Creates:
# .datalad/environments/mriqc/image.sif (alongside OCI directory)
```

Both formats can coexist; profiles reference the appropriate one.

---

## 5. Interface Changes

### containers-add

```bash
# Minimal (just register image)
datalad containers-add <name> --url <registry-url>

# With default profile
datalad containers-add <name> --url <registry-url> --default-profile apptainer-gpu

# Legacy call-fmt still works (becomes anonymous profile)
datalad containers-add <name> --url <registry-url> \
    --call-fmt "apptainer exec {img} {cmd}"
```

### containers-run

```bash
# Use default profile
datalad containers-run -n <name> <command>

# Use named profile
datalad containers-run -n <name> --profile <profile-name> <command>

# Override profile settings
datalad containers-run -n <name> --profile <profile> --runtime-args "<extra-args>" <command>

# Direct cmdexec (bypass profiles)
datalad containers-run -n <name> --cmdexec "<template>" <command>
```

### New Commands

```bash
# List available profiles
datalad containers-profiles

# Show profile details
datalad containers-profiles --show <profile-name>

# Convert image format
datalad containers-convert <name> --to <format>
```

---

## 6. Configuration Schema

```ini
# Dataset-level defaults
[datalad "execution"]
    default-profile = apptainer-default

# Profile definitions
[datalad "execution-profile.<name>"]
    runtime = apptainer | singularity | podman | docker
    template = <execution-template>
    runtime-args = <default-args>

# Container registration
[datalad "containers.<name>"]
    image = <path-to-image>
    source-url = <registry-url>
    source-registry = <registry-host>
    source-digest = <sha256-digest>
    format = oci | sif | simg
    default-profile = <profile-name>

# Container-specific profiles
[datalad "containers.<name>.profile.<profile-name>"]
    extends = <base-profile>
    runtime-args = <override-args>
```

---

## 7. Backward Compatibility

### Existing datasets continue to work

- `cmdexec` config key still honored (treated as anonymous profile)
- Old URL schemes (`dhub://`, `oci:docker://`) emit deprecation warning, still function
- Existing images don't need migration

### Migration path

```bash
# Suggested command to modernize config
datalad containers-migrate

# Updates:
# - dhub:// → docker://
# - oci:docker:// → docker://
# - cmdexec → named profile
# - Adds provenance metadata
```

---

## 8. Summary

| Aspect | Current | Proposed |
|--------|---------|----------|
| URL scheme | Mixed semantics | Protocol = registry |
| Storage format | Determined by URL | Native format from source |
| Provenance | Minimal | Full (registry, digest, timestamp) |
| Execution config | Baked in at add-time | Named profiles, runtime override |
| Runtime flexibility | Requires code changes | Profile selection |
| Run record | Shim invocation | Actual command |

---

## 9. Open Questions

1. **Profile inheritance** - Should profiles support `extends` for composition?

2. **Profile scope** - Dataset-local only, or also user-global (`~/.config/datalad/`)?

3. **Profile validation** - Warn if profile references unavailable runtime?

4. **Default profile** - What if no profile specified and no default set? Error or built-in fallback?

5. **Profile in provenance** - Store profile name, expanded command, or both?
