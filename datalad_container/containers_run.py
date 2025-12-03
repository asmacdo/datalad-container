"""Drop-in replacement for `datalad run` for command execution in a container"""

__docformat__ = 'restructuredtext'

import logging
import os.path as op
import sys

from datalad.core.local.run import (
    Run,
    get_command_pwds,
    normalize_command,
    run_command,
)
from datalad.distribution.dataset import (
    datasetmethod,
    require_dataset,
)
from datalad.interface.base import (
    Interface,
    build_doc,
    eval_results,
)
from datalad.interface.results import get_status_dict
from datalad.support.param import Parameter
from datalad.utils import ensure_iter

from datalad_container.find_container import find_container_
from datalad_container.profiles import load_profile, validate_profile

lgr = logging.getLogger("datalad.containers.containers_run")

# Environment variable to be set during execution to possibly
# inform underlying shim scripts about the original name of
# the container
CONTAINER_NAME_ENVVAR = 'DATALAD_CONTAINER_NAME'

_run_params = dict(
    Run._params_,
    container_name=Parameter(
        args=('-n', '--container-name',),
        metavar="NAME",
        doc="""Specify the name of or a path to a known container to use
        for execution, in case multiple containers are configured."""),
    image=Parameter(
        args=('--image',),
        metavar="NAME",
        doc="""Name of the image to use (e.g., 'alpine:latest' or 'mriqc:23.1.0').
        Resolves to .datalad/containers/images/<name>/<version>/image.
        When specified, --exec is required."""),
    exec_=Parameter(
        args=('--exec',),
        dest='exec_',
        metavar="TEMPLATE",
        doc="""Execution template string. Placeholders:
        {img} = Docker image name (datalad-container/name:version),
        {img_path} = OCI directory path (.datalad/containers/images/...),
        {cmd} = command to run.
        Examples: 'docker run --rm {img} {cmd}' or
        'apptainer exec oci:{img_path} {cmd}'.
        Required when --image is specified without --profile."""),
    profile=Parameter(
        args=('--profile',),
        metavar="NAME",
        doc="""Name of an execution profile in .datalad/containers/profiles/.
        Profiles define 'image' and 'exec' template. Can be overridden with
        --image and/or --exec flags. Example: 'docker-default'."""),
)


@build_doc
# all commands must be derived from Interface
class ContainersRun(Interface):
    # first docstring line is used a short description in the cmdline help
    # the rest is put in the verbose help and manpage
    """Drop-in replacement of 'run' to perform containerized command execution

    Container(s) need to be configured beforehand (see containers-add). If no
    container is specified and only one container is configured in the current
    dataset, it will be selected automatically. If more than one container is
    registered in the current dataset or to access containers from subdatasets,
    the container has to be specified.

    A command is generated based on the input arguments such that the
    container image itself will be recorded as an input dependency of
    the command execution in the `run` record in the git history.

    During execution the environment variable {name_envvar} is set to the
    name of the used container.
    """

    _docs_ = dict(
        name_envvar=CONTAINER_NAME_ENVVAR
    )

    _params_ = _run_params

    # Analogous to 'run' command - stop on first error
    on_failure = 'stop'

    @staticmethod
    @datasetmethod(name='containers_run')
    @eval_results
    def __call__(cmd, container_name=None, dataset=None,
                 inputs=None, outputs=None, message=None, expand=None,
                 explicit=False, sidecar=None, image=None, exec_=None,
                 profile=None):
        from unittest.mock import \
            patch  # delayed, since takes long (~600ms for yoh)
        pwd, _ = get_command_pwds(dataset)
        ds = require_dataset(dataset, check_installed=True,
                             purpose='run a containerized command execution')

        # Phase 3: Load profile and merge with CLI overrides
        if profile is not None:
            try:
                profile_data = load_profile(ds, profile)
            except FileNotFoundError as exc:
                yield get_status_dict(
                    'run',
                    ds=ds,
                    status='error',
                    message=str(exc))
                return
            except ValueError as exc:
                yield get_status_dict(
                    'run',
                    ds=ds,
                    status='error',
                    message=str(exc))
                return

            # CLI overrides take precedence over profile
            if image is None:
                image = profile_data.get('image')
            if exec_ is None:
                exec_ = profile_data.get('exec')

            # Validate image exists (error early)
            try:
                validate_profile({'image': image, 'exec': exec_, '_name': profile}, ds)
            except ValueError as exc:
                yield get_status_dict(
                    'run',
                    ds=ds,
                    status='error',
                    message=str(exc))
                return

        # New Phase 2 path: --image and --exec specified directly
        if image is not None:
            if exec_ is None:
                yield get_status_dict(
                    'run',
                    ds=ds,
                    status='error',
                    message='--exec is required when --image is specified')
                return

            # Parse image name:version
            if ':' in image:
                base_name, version = image.split(':', 1)
            else:
                base_name, version = image, 'latest'

            # Resolve paths and names
            docker_image = f"datalad-container/{base_name}:{version}"
            image_path = f".datalad/containers/images/{base_name}/{version}/image"

            # Expand placeholders in exec template
            cmd = normalize_command(cmd)
            try:
                resolved_cmd = exec_.format(
                    img=docker_image,
                    img_path=image_path,
                    cmd=cmd,
                )
            except KeyError as exc:
                yield get_status_dict(
                    'run',
                    ds=ds,
                    status='error',
                    message=('Unrecognized --exec placeholder: %s. '
                             'Available: {img}, {img_path}, {cmd}', exc))
                return

            with patch.dict('os.environ',
                            {CONTAINER_NAME_ENVVAR: image}):
                for r in run_command(
                        cmd=resolved_cmd,
                        dataset=dataset or (ds if ds.path == pwd else None),
                        inputs=inputs,
                        extra_inputs=[image_path],
                        outputs=outputs,
                        message=message,
                        expand=expand,
                        explicit=explicit,
                        sidecar=sidecar):
                    yield r
            return

        # Legacy path: use -n/--container-name with config lookup
        # this following block locates the target container. this involves a
        # configuration look-up. This is not using
        # get_container_configuration(), because it needs to account for a
        # wide range of scenarios, including the installation of the dataset(s)
        # that will eventually provide (the configuration) for the container.
        # However, internally this is calling `containers_list()`, which is
        # using get_container_configuration(), so any normalization of
        # configuration on-read, get still be implemented in this helper.
        container = None
        for res in find_container_(ds, container_name):
            if res.get("action") == "containers":
                container = res
            else:
                yield res
        assert container, "bug: container should always be defined here"

        image_path = op.relpath(container["path"], pwd)
        # container record would contain path to the (sub)dataset containing
        # it.  If not - take current dataset, as it must be coming from it
        image_dspath = op.relpath(container.get('parentds', ds.path), pwd)

        # sure we could check whether the container image is present,
        # but it might live in a subdataset that isn't even installed yet
        # let's leave all this business to `get` that is called by `run`

        cmd = normalize_command(cmd)
        # expand the command with container execution
        if 'cmdexec' in container:
            callspec = container['cmdexec']

            # Temporary kludge to give a more helpful message
            if callspec.startswith("["):
                import json
                try:
                    json.loads(callspec)
                except json.JSONDecodeError:
                    pass  # Never mind, false positive.
                else:
                    raise ValueError(
                        'cmdexe {!r} is in an old, unsupported format. '
                        'Convert it to a plain string.'.format(callspec))
            try:
                cmd_kwargs = dict(
                    # point to the python installation that runs *this* code
                    # we know that it would have things like the docker
                    # adaptor installed with this extension package
                    python=sys.executable,
                    img=image_path,
                    cmd=cmd,
                    img_dspath=image_dspath,
                    img_dirpath=op.dirname(image_path) or ".",
                )
                cmd = callspec.format(**cmd_kwargs)
            except KeyError as exc:
                yield get_status_dict(
                    'run',
                    ds=ds,
                    status='error',
                    message=(
                        'Unrecognized cmdexec placeholder: %s. '
                        'See containers-add for information on known ones: %s',
                        exc,
                        ", ".join(cmd_kwargs)))
                return
        else:
            # just prepend and pray
            cmd = container['path'] + ' ' + cmd

        extra_inputs = []
        for extra_input in ensure_iter(container.get("extra-input",[]), set):
            try:
                xi_kwargs = dict(
                    img_dspath=image_dspath,
                    img_dirpath=op.dirname(image_path) or ".",
                )
                extra_inputs.append(extra_input.format(**xi_kwargs))
            except KeyError as exc:
                yield get_status_dict(
                    'run',
                    ds=ds,
                    status='error',
                    message=(
                        'Unrecognized extra_input placeholder: %s. '
                        'See containers-add for information on known ones: %s',
                        exc,
                        ", ".join(xi_kwargs)))
                return

        lgr.debug("extra_inputs = %r", extra_inputs)

        with patch.dict('os.environ',
                        {CONTAINER_NAME_ENVVAR: container['name']}):
            # fire!
            for r in run_command(
                    cmd=cmd,
                    dataset=dataset or (ds if ds.path == pwd else None),
                    inputs=inputs,
                    extra_inputs=[image_path] + extra_inputs,
                    outputs=outputs,
                    message=message,
                    expand=expand,
                    explicit=explicit,
                    sidecar=sidecar):
                yield r
