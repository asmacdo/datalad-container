"""List execution profiles known to a dataset"""

__docformat__ = 'restructuredtext'

import logging
import os.path as op

import datalad.support.ansi_colors as ac
from datalad.distribution.dataset import (
    EnsureDataset,
    datasetmethod,
    require_dataset,
)
from datalad.interface.base import (
    Interface,
    build_doc,
    eval_results,
)
from datalad.interface.results import get_status_dict
from datalad.interface.utils import default_result_renderer
from datalad.support.constraints import EnsureNone
from datalad.support.param import Parameter
from datalad.ui import ui

from datalad_container.profiles import list_profiles, load_profile

lgr = logging.getLogger("datalad.containers.containers_profiles")


@build_doc
class ContainersProfiles(Interface):
    """List execution profiles known to a dataset

    Profiles are YAML files in .datalad/containers/profiles/ that define
    'image' and 'exec' template for running containers.
    """

    result_renderer = 'tailored'

    _params_ = dict(
        dataset=Parameter(
            args=("-d", "--dataset"),
            doc="""specify the dataset to query. If no dataset is given, an
            attempt is made to identify the dataset based on the current
            working directory""",
            constraints=EnsureDataset() | EnsureNone()),
    )

    @staticmethod
    @datasetmethod(name='containers_profiles')
    @eval_results
    def __call__(dataset=None):
        ds = require_dataset(dataset, check_installed=True,
                             purpose='list profiles')
        refds = ds.path

        profiles = list_profiles(ds)

        for p in profiles:
            # Load profile to get resolved image/exec
            try:
                profile_data = load_profile(ds, p['name'])
                image = profile_data.get('image', '')
                exec_ = profile_data.get('exec', '')
                extends = None
                # Check if this profile extends another
                with open(op.join(ds.path, p['path'])) as f:
                    import yaml
                    raw = yaml.safe_load(f)
                    extends = raw.get('extends') if raw else None
            except Exception as exc:
                lgr.warning("Failed to load profile %s: %s", p['name'], exc)
                image = '<error>'
                exec_ = '<error>'
                extends = None

            res = get_status_dict(
                status='ok',
                action='containers_profiles',
                name=p['name'],
                type='file',
                path=op.join(ds.path, p['path']),
                refds=refds,
                parentds=ds.path,
                image=image,
                exec=exec_,
            )
            if extends:
                res['extends'] = extends
            yield res

    @staticmethod
    def custom_result_renderer(res, **kwargs):
        if res["action"] != "containers_profiles":
            default_result_renderer(res)
        else:
            extends_info = ""
            if res.get("extends"):
                extends_info = f" (extends: {res['extends']})"
            ui.message(
                "{name}{extends} -> {image}"
                .format(
                    name=ac.color_word(res["name"], ac.MAGENTA),
                    extends=extends_info,
                    image=res.get("image", "<not set>")))
