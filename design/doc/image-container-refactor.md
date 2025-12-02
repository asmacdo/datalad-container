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

**Open question:** How to handle custom/private registries? Options:
- `oci://registry.example.com/org/repo:tag` - generic OCI protocol
- `docker://registry.example.com/org/repo:tag` - registry in path
- New protocol per registry (doesn't scale)

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

**Provenance stored in consolidated sources.yaml per image:**

```yaml
# .datalad/containers/images/mriqc/sources.yaml

versions:
  23.1.0:
    url: docker://nipreps/mriqc:23.1.0
    digest: sha256:abc123def456...
    fetched: 2024-01-15T10:30:00Z
  24.0.0:
    url: docker://nipreps/mriqc:24.0.0
    digest: sha256:def456789...
    fetched: 2024-02-20T14:00:00Z
```

**Why YAML files instead of .datalad/config?**
- YAML supports richer structures (lists, nested objects)
- Each image/profile is a separate, self-contained unit
- Easier to read, share, and version independently
- Cleaner git diffs
- Can include comments/documentation
- Profiles can be copied between projects

**Git-annex integration:**

For OCI images, individual layers get registry URLs for efficient retrieval:
```bash
git annex whereis .datalad/containers/images/mriqc/23.1.0/image/blobs/sha256/abc123
# → docker.io/nipreps/mriqc@sha256:abc123
```

---

## 3. Execution Profiles

### Current Problem

Execution configuration is either:
- Hardcoded in Python (`docker_run()` with fixed flags)
  - Problem becomes worse with other runtimes, ie `podman_run()`
- Baked into cmdexec at add-time (inflexible)
  - Can be changed, but requires knowledge of datalad-containers internals
- Hidden from provenance (shim invocation recorded, not actual command)

Scientists need to run the same image with different configurations:
- GPU vs CPU
- Different volume mounts
- Different runtimes (apptainer on HPC, podman on laptop)

### Proposed Solution

**Two concepts only:**

1. **Image** - artifact with provenance, no execution semantics
2. **Profile** - execution recipe that references an image, can extend other profiles

**Key design decisions:**
- Profiles point to images (not images to profiles)
- Profiles can extend other profiles
- Child profiles **clobber** parent values (no merging)
- Provenance records the resolved command, not just profile name

### Profile Structure

Profiles are YAML files in `.datalad/containers/profiles/`:

```yaml
# .datalad/containers/profiles/mriqc.yaml
# Base MRIQC profile (shipped by ReproNim/containers)

image: mriqc/23.1.0
exec: apptainer exec --cleanenv {img} {cmd}
```

```yaml
# .datalad/containers/profiles/mriqc-myexperiment.yaml
# User's experiment-specific profile

extends: mriqc
exec: apptainer exec --cleanenv --nv --bind /data/myexp:/input {img} {cmd}
```

**Clobber semantics:** The child's `exec` completely replaces the parent's. If you want the parent's flags plus yours, you copy them explicitly. No magic merging.

### Cross-Dataset Extension

Profiles can extend profiles from subdatasets (e.g., ReproNim/containers):

```yaml
# my-analysis/.datalad/containers/profiles/mriqc-myexperiment.yaml

extends: inputs/containers/.datalad/containers/profiles/mriqc.yaml
exec: apptainer exec --cleanenv --nv --bind /data/myexp:/input {img} {cmd}
```

The path is explicit and unambiguous. Git tracks the subdataset relationship.

### Profile Usage

```bash
# Run with a profile
datalad containers-run --profile mriqc-myexperiment \
    mriqc /input /output participant

# Override exec at runtime (bypass profile)
datalad containers-run --profile mriqc \
    --exec "apptainer exec --nv {img} {cmd}" \
    mriqc /input /output participant
```

### Provenance

Run records capture the **resolved execution command**:

```json
{
  "cmd": "apptainer exec --cleanenv --nv --bind /data/myexp:/input oci:.datalad/containers/images/mriqc/23.1.0/image mriqc /input /output participant",
  "profile": "mriqc-myexperiment",
  "profile-source": ".datalad/containers/profiles/mriqc-myexperiment.yaml"
}
```

The `cmd` is what actually ran. The profile reference is informational.

---

## 4. Image Format Handling

### OCI Images (from Docker/Quay/GHCR registries)

```bash
datalad containers-add mriqc --url docker://nipreps/mriqc:23.1.0
```

Storage:
```
.datalad/containers/images/mriqc/23.1.0/
└── image/                    # OCI directory
    ├── blobs/sha256/...     # Layers (git-annex tracked)
    ├── index.json
    └── oci-layout
```

### Singularity Images (from Singularity Hub or local)

```bash
datalad containers-add dcm2niix --url shub://neurodebian/dcm2niix:latest
datalad containers-add custom --url /path/to/custom.sif
```

Storage:
```
.datalad/containers/images/dcm2niix/latest/
└── image.sif                # Single file (git-annex tracked)
```

### Format Conversion

Optional conversion for optimization:

```bash
# Convert OCI to SIF (for HPC performance)
datalad containers-convert mriqc/23.1.0 --to sif

# Creates:
# .datalad/containers/images/mriqc/23.1.0/image.sif (alongside OCI directory)
```

Both formats can coexist; profiles reference the appropriate one.

---

## 5. File Layout

```
.datalad/containers/
├── images/
│   ├── mriqc/
│   │   ├── sources.yaml          # Provenance for all versions
│   │   ├── 23.1.0/
│   │   │   ├── image/            # OCI directory
│   │   │   └── image.sif         # Optional converted SIF
│   │   └── 24.0.0/
│   │       └── image/
│   └── fmriprep/
│       ├── sources.yaml
│       └── 23.2.0/
│           └── image/
└── profiles/
    ├── mriqc.yaml                # Base profile (references mriqc/23.1.0)
    └── mriqc-myexperiment.yaml   # User's extension
```

Everything under `.datalad/containers/`. No separate `environments/` directory.

---

## 6. Interface Changes

### containers-add

```bash
# Add image from registry
datalad containers-add mriqc --url docker://nipreps/mriqc:23.1.0
# Creates: .datalad/containers/images/mriqc/23.1.0/ + updates sources.yaml

# Add another version
datalad containers-add mriqc --url docker://nipreps/mriqc:24.0.0
# Creates: .datalad/containers/images/mriqc/24.0.0/ + updates sources.yaml
```

### containers-run

```bash
# Run with profile
datalad containers-run --profile <profile-name> <command>

# Override exec
datalad containers-run --profile <profile-name> --exec "<template>" <command>

# Direct exec (no profile, must specify image)
datalad containers-run --image <image-name> --exec "<template>" <command>
```

### New commands

```bash
# List images
datalad containers-images

# List profiles
datalad containers-profiles

# Convert image format
datalad containers-convert <image-name> --to sif
```

---

## 7. Backward Compatibility

### Existing datasets continue to work

- `cmdexec` in .datalad/config still honored (treated as inline exec)
- Old URL schemes (`dhub://`, `oci:docker://`) emit deprecation warning, still function
- Existing images don't need migration

### Migration path

```bash
# Suggested command to modernize config
datalad containers-migrate

# Updates:
# - Converts .datalad/config entries to YAML files
# - dhub:// → docker://
# - oci:docker:// → docker://
# - Creates profile from cmdexec
```

---

## 8. Summary

| Aspect | Current | Proposed |
|--------|---------|----------|
| URL scheme | Mixed semantics | Protocol = registry |
| Storage format | Determined by URL | Native format from source |
| Provenance | Minimal, in config | Full, in YAML files |
| Execution config | Baked in at add-time | Separate profiles |
| Profile reuse | Not possible | Extend other profiles (clobber) |
| Run record | Shim invocation | Actual command |
| Configuration | .datalad/config (INI) | YAML files |

---

## 9. Open Questions

1. **Custom registries** - How to specify private/custom OCI registries?

2. **Profile discovery** - How to list available profiles from subdatasets?

3. **Profile validation** - Warn if profile references unavailable image or runtime?

4. **Placeholder expansion** - What placeholders beyond `{img}` and `{cmd}`? (`{pwd}`, `{uid}`?)

5. **Image format conversion** - On-demand or explicit `containers-convert` command?
