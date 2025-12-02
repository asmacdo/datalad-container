# ReproNim/containers Integration with Refactored datalad-container

This document describes how ReproNim/containers can leverage the refactored datalad-container architecture.

---

## New Capabilities

### 1. Multiple Image Formats and Versions

With native format storage and versioned image directories, ReproNim can provide:

**Multiple versions per image:**
```
.datalad/containers/images/
├── mriqc/
│   ├── sources.yaml
│   ├── 23.1.0/
│   │   ├── image/          # OCI directory
│   │   └── image.sif       # Optional SIF
│   └── 24.0.0/
│       └── image/
└── fmriprep/
    ├── sources.yaml
    ├── 23.2.0/
    │   └── image/
    └── 24.1.0/
        └── image/
```

### Benefits of OCI format for ReproNim:

- **Layer deduplication** - Many neuroimaging containers share base layers
- **Incremental updates** - Only changed layers need to be fetched
- **Registry retrieval** - git-annex can fetch layers directly from Docker Hub
- **Multi-runtime** - Works with apptainer, podman, docker without conversion

---

## 2. Execution Profiles

ReproNim ships curated base profiles alongside images. Users extend these for their specific needs.

### ReproNim Base Profiles

```yaml
# .datalad/containers/profiles/mriqc.yaml
# Base MRIQC profile - sane defaults for most users

image: mriqc/23.1.0
exec: apptainer exec --cleanenv {img} {cmd}
```

```yaml
# .datalad/containers/profiles/fmriprep.yaml
# Base fMRIPrep profile

image: fmriprep/23.2.0
exec: apptainer exec --cleanenv {img} {cmd}
```

### User Extensions

Users create their own profiles that extend ReproNim's base:

```yaml
# my-analysis/.datalad/containers/profiles/mriqc-mylab.yaml

extends: inputs/containers/.datalad/containers/profiles/mriqc.yaml
exec: apptainer exec --cleanenv --nv --bind /scratch:/scratch --bind /data/mylab:/input {img} {cmd}
```

```yaml
# my-analysis/.datalad/containers/profiles/mriqc-gpu.yaml

extends: inputs/containers/.datalad/containers/profiles/mriqc.yaml
exec: apptainer exec --cleanenv --nv {img} {cmd}
```

**Key point:** ReproNim provides the base. Users clobber `exec` with their environment-specific settings. No runtime-specific profiles (apptainer-gpu, podman-default, etc.) - users know what they need.

---

## 3. Dataset Structure

### Proposed ReproNim/containers layout:

```
ReproNim/containers/
├── .datalad/containers/
│   ├── images/
│   │   ├── mriqc/
│   │   │   ├── sources.yaml
│   │   │   ├── 23.1.0/
│   │   │   │   ├── image/
│   │   │   │   └── image.sif
│   │   │   └── 24.0.0/
│   │   │       └── image/
│   │   └── fmriprep/
│   │       ├── sources.yaml
│   │       ├── 23.2.0/
│   │       │   └── image/
│   │       └── 24.1.0/
│   │           └── image/
│   └── profiles/
│       ├── mriqc.yaml
│       ├── mriqc-24.yaml
│       ├── fmriprep.yaml
│       └── fmriprep-24.yaml
│
├── scripts/
│   ├── singularity_cmd          # Isolated execution wrapper (existing)
│   └── freeze_versions          # Version pinning tool
│
└── README.md
```

### sources.yaml Example

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

---

## 4. Workflow Examples

### Basic Usage

```bash
# Get ReproNim containers
datalad clone https://github.com/ReproNim/containers inputs/containers

# List available images and profiles
datalad containers-images -d inputs/containers
datalad containers-profiles -d inputs/containers

# Run with base profile
datalad containers-run -d inputs/containers --profile mriqc \
    mriqc /bids /outputs participant
```

### Creating a Lab-Specific Profile

```bash
# Create your own profile extending ReproNim's base
mkdir -p .datalad/containers/profiles
cat > .datalad/containers/profiles/mriqc-mylab.yaml << 'EOF'
extends: inputs/containers/.datalad/containers/profiles/mriqc.yaml
exec: apptainer exec --cleanenv --nv --bind /scratch:/scratch --bind /gpfs/mylab:/data {img} {cmd}
EOF

# Use it
datalad containers-run --profile mriqc-mylab \
    mriqc /data/bids /data/outputs participant
```

### One-Off Override

```bash
# Use base profile but override exec for this run
datalad containers-run -d inputs/containers --profile mriqc \
    --exec "apptainer exec --cleanenv --nv {img} {cmd}" \
    mriqc /bids /outputs participant
```

### Using a Specific Version

```bash
# Create profile for newer version
cat > .datalad/containers/profiles/mriqc-24.yaml << 'EOF'
image: mriqc/24.0.0
exec: apptainer exec --cleanenv {img} {cmd}
EOF

datalad containers-run --profile mriqc-24 \
    mriqc /bids /outputs participant
```

---

## 5. Migration Path

### Phase 1: Add new structure (non-breaking)

- Add `.datalad/containers/images/` with versioned directories
- Add `.datalad/containers/profiles/` YAML files
- Add OCI images alongside existing SIF files
- Keep existing `.datalad/config` entries

### Phase 2: Recommend new approach

- Default documentation uses profiles
- Legacy config still works
- Add migration guide

### Phase 3: Simplify storage

- Consider generating SIF on-demand with `containers-convert`
- Or keep both for user convenience

---

## 6. Benefits Summary

| Aspect | Current | With Refactor |
|--------|---------|---------------|
| Image formats | SIF only | SIF + OCI |
| Image versions | Flat naming | Structured versioning |
| Layer sharing | None | Deduplication across containers |
| Execution config | Hardcoded in wrapper | Base profiles, user-extendable |
| Runtime flexibility | Singularity only | Any runtime via profile |
| Provenance | Wrapper invocation | Actual command recorded |
| Customization | Fork or edit wrapper | Extend profile, clobber exec |
| HPC adaptation | Manual | User creates their own profile |

---

## 7. Open Questions for ReproNim

1. **Dual format storage** - Ship both OCI and SIF, or OCI-only with on-demand conversion?

2. **Base profile scope** - Just image + minimal exec, or include common bind mounts?

3. **Profile per version** - One profile per version (mriqc-23.yaml, mriqc-24.yaml) or update profile to point to latest?

4. **Backward compatibility** - How long to maintain legacy `.datalad/config` entries?

5. **singularity_cmd wrapper** - Keep as option in profiles, or phase out in favor of explicit exec?
