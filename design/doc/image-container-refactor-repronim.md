# ReproNim/containers Integration with Refactored datalad-container

This document describes how ReproNim/containers can leverage the refactored datalad-container architecture.

---

## New Capabilities

### 1. Multiple Image Formats

With native format storage, ReproNim can now provide:

**Singularity/SIF images** (current approach):
```
images/
├── bids-mriqc.sif
├── bids-fmriprep.sif
└── bids-freesurfer.sif
```

**OCI images** (new capability):
```
images/
├── bids-mriqc/
│   └── image/           # OCI directory
│       ├── blobs/
│       ├── index.json
│       └── oci-layout
└── bids-fmriprep/
    └── image/
```

**Both in the same dataset:**
```
images/
├── bids-mriqc.sif                    # For HPC users who want single file
├── bids-mriqc/image/                 # For users who want OCI layers
├── bids-fmriprep.sif
└── bids-fmriprep/image/
```

### Benefits of OCI format for ReproNim:

- **Layer deduplication** - Many neuroimaging containers share base layers
- **Incremental updates** - Only changed layers need to be fetched
- **Registry retrieval** - git-annex can fetch layers directly from Docker Hub
- **Multi-runtime** - Works with apptainer, podman, docker without conversion

---

## 2. Execution Profiles

ReproNim can ship curated execution profiles alongside images.

### Profile Library

```ini
# .datalad/config in ReproNim/containers

# ============================================
# Base profiles (runtime-specific defaults)
# ============================================

[datalad "execution-profile.repronim-apptainer"]
    runtime = apptainer
    template = {scripts}/singularity_cmd exec {img} {cmd}
    description = "ReproNim isolated Apptainer execution"

[datalad "execution-profile.repronim-apptainer-gpu"]
    runtime = apptainer
    template = {scripts}/singularity_cmd exec --nv {img} {cmd}
    description = "ReproNim isolated Apptainer with GPU"

[datalad "execution-profile.repronim-singularity"]
    runtime = singularity
    template = {scripts}/singularity_cmd exec {img} {cmd}
    description = "ReproNim isolated Singularity execution"

[datalad "execution-profile.repronim-docker"]
    runtime = docker
    template = docker run --rm -v {pwd}:/work -w /work {img} {cmd}
    description = "Docker execution"

# ============================================
# Container-specific profiles
# ============================================

[datalad "containers.bids-mriqc.profile.default"]
    extends = repronim-apptainer
    description = "Standard MRIQC execution"

[datalad "containers.bids-mriqc.profile.hpc"]
    extends = repronim-apptainer
    runtime-args = --bind /scratch:/scratch --bind /work:/work
    description = "MRIQC for HPC with scratch space"

[datalad "containers.bids-mriqc.profile.gpu"]
    extends = repronim-apptainer-gpu
    description = "MRIQC with GPU support"

[datalad "containers.bids-fmriprep.profile.default"]
    extends = repronim-apptainer
    description = "Standard fMRIPrep execution"

[datalad "containers.bids-fmriprep.profile.hpc-large"]
    extends = repronim-apptainer
    runtime-args = --bind /scratch:/scratch --memory 64G
    description = "fMRIPrep for large datasets on HPC"
```

### Usage in Downstream Datasets

```bash
# Clone ReproNim containers
datalad clone https://github.com/ReproNim/containers inputs/containers

# In your analysis dataset, use ReproNim's curated profiles
datalad containers-run \
    -d inputs/containers \
    -n bids-mriqc \
    --profile hpc \
    mriqc /data /outputs participant

# Or override for your specific HPC
datalad containers-run \
    -d inputs/containers \
    -n bids-mriqc \
    --profile hpc \
    --runtime-args "--bind /gpfs:/gpfs" \
    mriqc /data /outputs participant
```

---

## 3. Dataset Structure

### Proposed ReproNim/containers layout:

```
ReproNim/containers/
├── .datalad/
│   ├── config                    # Container registrations + profiles
│   └── environments/             # Legacy location (backward compat)
│
├── images/                       # New image storage location
│   ├── bids-mriqc/
│   │   ├── image/               # OCI directory
│   │   ├── image.sif            # Optional SIF (for HPC convenience)
│   │   └── metadata.json        # Provenance
│   │
│   ├── bids-fmriprep/
│   │   ├── image/
│   │   ├── image.sif
│   │   └── metadata.json
│   │
│   └── bids-freesurfer/
│       ├── image/
│       └── metadata.json
│
├── scripts/
│   ├── singularity_cmd          # Isolated execution wrapper
│   ├── freeze_versions          # Version pinning tool
│   └── check_runtime            # Runtime availability checker
│
├── profiles/                     # Optional: profile documentation
│   ├── README.md
│   ├── hpc-examples.md
│   └── gpu-setup.md
│
└── README.md
```

### Configuration:

```ini
# .datalad/config

# Dataset defaults
[datalad "execution"]
    default-profile = repronim-apptainer
    scripts-path = scripts

# Container registrations
[datalad "containers.bids-mriqc"]
    image = images/bids-mriqc/image
    image-sif = images/bids-mriqc/image.sif
    source-url = docker://nipreps/mriqc:23.1.0
    source-digest = sha256:abc123...
    format = oci
    default-profile = bids-mriqc.default

[datalad "containers.bids-fmriprep"]
    image = images/bids-fmriprep/image
    image-sif = images/bids-fmriprep/image.sif
    source-url = docker://nipreps/fmriprep:23.2.0
    source-digest = sha256:def456...
    format = oci
    default-profile = bids-fmriprep.default

# Profiles (as shown above)
[datalad "execution-profile.repronim-apptainer"]
    # ...
```

---

## 4. Workflow Examples

### Basic Usage

```bash
# Get ReproNim containers
datalad clone https://github.com/ReproNim/containers

# List available containers
datalad containers-list -d containers

# List available profiles
datalad containers-profiles -d containers

# Run with default profile
datalad containers-run -d containers -n bids-mriqc \
    mriqc /bids /outputs participant
```

### HPC Workflow

```bash
# Clone into project
datalad clone https://github.com/ReproNim/containers inputs/containers

# Check which profiles are available
datalad containers-profiles -d inputs/containers --show bids-fmriprep

# Run with HPC profile
datalad run \
    --input inputs/bids \
    --input inputs/containers/images/bids-fmriprep \
    --output outputs/fmriprep \
    "$(datalad containers-run -d inputs/containers -n bids-fmriprep --profile hpc --dry-run \
        fmriprep /inputs/bids /outputs/fmriprep participant)"
```

### GPU Workflow

```bash
# Use GPU profile
datalad containers-run -d containers -n bids-mriqc \
    --profile gpu \
    mriqc /bids /outputs participant
```

### Custom Override

```bash
# Start from HPC profile, add custom binds
datalad containers-run -d containers -n bids-fmriprep \
    --profile hpc \
    --runtime-args "--bind /project/mylab:/project" \
    fmriprep /bids /outputs participant
```

---

## 5. Migration Path

### Phase 1: Add OCI support (non-breaking)

- Add OCI images alongside existing SIF files
- Add execution profiles to config
- Update documentation

```
images/
├── bids-mriqc.sing              # Existing (keep)
├── bids-mriqc/image/            # New OCI directory
```

### Phase 2: Recommend OCI + profiles

- Default documentation uses OCI + profiles
- SIF files still available for backward compatibility
- Add migration guide

### Phase 3: Optimize storage

- Consider removing duplicate SIF files
- Or generate SIF on-demand with `containers-convert`

---

## 6. Benefits Summary

| Aspect | Current | With Refactor |
|--------|---------|---------------|
| Image formats | SIF only | SIF + OCI |
| Layer sharing | None | Deduplication across containers |
| Execution config | Hardcoded in singularity_cmd | Named profiles, user-overridable |
| Runtime flexibility | Singularity only | Apptainer, Singularity, Podman, Docker |
| Provenance | Wrapper invocation | Actual command recorded |
| Customization | Fork or edit wrapper | Override profile at runtime |
| HPC adaptation | Manual | Profile selection |

---

## 7. Open Questions for ReproNim

1. **Dual format storage** - Ship both OCI and SIF, or OCI-only with on-demand conversion?

2. **Profile curation** - Who maintains profiles? How are they tested?

3. **Profile naming** - `repronim-*` prefix for ReproNim-curated profiles?

4. **Backward compatibility** - How long to maintain legacy `.sing` files?

5. **Profile documentation** - Inline in config, or separate docs?

6. **Default runtime** - Apptainer as default, or require explicit selection?
