"""Utilities for reading 'generic' physiological BIDS data."""

import gzip
import json
from pathlib import Path
from warnings import warn

import numpy as np
from mne.utils import _check_option, _validate_type


def _get_physio_type(physio_json_fpath):
    """Return the type of data that is stored in a <match>_physio.tsv file.

    https://bids-specification.readthedocs.io/en/latest/glossary.html#physiotypegeneric-enums
    """  # noqa: E501
    default = "generic"
    info = _read_json(physio_json_fpath)
    physio_type = info.get("PhysioType", None)  # e.g. "eyetracking"

    if not physio_type:
        warn(
            "Expected a key labeled 'PhysioType', with a value such as 'eyetrack', but "
            f"none exists. Falling back to {default}:\n  Files {physio_json_fpath.name}"
        )
        physio_type = default
    _validate_type(physio_type, str, "physio_type")
    return physio_type


def _read_json(physio_json_fpath):
    physio_json_fpath = Path(physio_json_fpath)
    encoding = "utf-8-sig"
    info = json.loads(physio_json_fpath.read_text(encoding=encoding))
    return info


def _read_physioevents(bids_path, ch_names="auto"):
    """Read a ``*_physioevents.tsv(.gz)`` sidecar and return annotation kwargs.

    Parameters
    ----------
    bids_path : mne_bids.BIDSPath
        Path that resolves to one physio recording (e.g. ``recording-eye1``).
    ch_names : tuple of str | list of str | None | "auto"
        Channel names to associate with each event annotation. If ``"auto"``,
        channel names are inferred from the corresponding ``*_physio.json``
        sidecar ``"Columns"`` key exactly as provided. If ``None``, no specific
        channel names will be associated with the annotations.

    Returns
    -------
    annot_kwargs : dict of ndarray
        Keyword arguments suitable for ``mne.Annotations(**annot_kwargs)``.
    """
    from mne_bids.read import _make_annotation_kwargs
    from mne_bids.tsv_handler import _from_tsv

    encoding = "utf-8-sig"

    _validate_type(ch_names, (list, tuple, str, type(None)), item_name="ch_names")
    physio_json_fpath = bids_path.find_matching_sidecar(
        suffix="physio", extension=".json"
    )
    physio_sidecar = _read_json(physio_json_fpath)

    # Make annotations channel-agnostic
    if ch_names is None:
        ch_names = tuple()
    # Pull names from TSV file. Assumes MNE ch_names are identical to these column names
    elif ch_names == "auto":
        ch_names = tuple(
            name for name in physio_sidecar["Columns"] if name != "timestamp"
        )
    # MNE channel names were passed in from the call site
    else:
        ch_names = tuple(ch_names)

    events_fname = bids_path.find_matching_sidecar(
        suffix="physioevents",
        extension=".tsv.gz",
    )

    events = _from_tsv(events_fname)
    events.setdefault("duration", ["0"] * len(events["onset"]))
    annot_kwargs, _ = _make_annotation_kwargs(events, events_fname)
    events_json = _read_json(events_fname.with_suffix("").with_suffix(".json"))
    source = events_json["OnsetSource"]
    if source == "n/a":
        annot_kwargs["onset"] /= physio_sidecar["SamplingFrequency"]
    else:
        columns = physio_sidecar["Columns"]
        _check_option("OnsetSource", source, columns)
        unit = physio_sidecar.get(source, {}).get("Units")
        scales = {"s": 1, "ms": 1e-3, "us": 1e-6, "µs": 1e-6, "ns": 1e-9}
        if unit is None:
            from scipy.interpolate import interp1d

            timestamps = np.asarray(_from_tsv(bids_path.fpath, dtypes=float)[source])
            if (
                len(timestamps) < 2
                or not np.isfinite(timestamps).all()
                or np.any(np.diff(timestamps) <= 0)
            ):
                raise ValueError("OnsetSource must increase between samples.")
            to_seconds = interp1d(
                timestamps,
                np.arange(len(timestamps)) / physio_sidecar["SamplingFrequency"],
                bounds_error=False,
                fill_value="extrapolate",
                assume_sorted=True,
            )
            annot_kwargs["onset"] = to_seconds(annot_kwargs["onset"])
        else:
            _check_option("OnsetSource units", unit, scales)
            with gzip.open(bids_path.fpath, "rt", encoding=encoding) as fid:
                first = float(fid.readline().split("\t")[columns.index(source)])
            annot_kwargs["onset"] = (annot_kwargs["onset"] - first) * scales[unit]
    n_annots = len(annot_kwargs["onset"])
    tuples = [ch_names] * n_annots
    arr = np.empty(n_annots, dtype=object)
    arr[:] = tuples
    annot_kwargs["ch_names"] = arr

    return annot_kwargs
