===============================
``find_matching_paths`` review
===============================

Overview
--------

The public helper :func:`mne_bids.find_matching_paths` loads every file below a
user-supplied BIDS root and filters the resulting list with
:func:`mne_bids.path._filter_fnames`. The function therefore spends most of its
time in three steps:

1. :func:`mne_bids.path._return_root_paths` walks the tree and materialises all
   matching :class:`pathlib.Path` objects in memory before any entity filtering
   takes place.【F:mne_bids/path.py†L2521-L2611】
2. :func:`mne_bids.path._filter_fnames` converts each path to a string and runs
   a single large regular expression to decide which files should survive the
   filter.【F:mne_bids/path.py†L2403-L2428】
3. :func:`mne_bids.path._fnames_to_bidspaths` re-parses the surviving paths into
   :class:`mne_bids.BIDSPath` instances.

The current implementation keeps the logic self-contained but repeatedly scans
entire directory trees and performs relatively expensive regex matching on every
call. On a synthetic dataset with eight subjects, the public helpers in
``mne_bids.path`` exhibit the following relative runtime ordering (5 iterations
per function):【2111f3†L1-L10】

.. code-block:: text

   get_entities_from_fname: 0.0000s (avg per call 0.0000s)
   get_bids_path_from_fname: 0.0009s (avg per call 0.0002s)
   get_datatypes: 0.0023s (avg per call 0.0005s)
   get_entity_vals_task: 0.0084s (avg per call 0.0017s)
   search_folder_for_text: 0.0085s (avg per call 0.0017s)
   get_entity_vals_session: 0.0087s (avg per call 0.0017s)
   find_matching_paths_meg: 0.0291s (avg per call 0.0058s)
   find_matching_paths_ignore: 0.0547s (avg per call 0.0109s)
   find_matching_paths: 0.0557s (avg per call 0.0111s)

The standard ``find_matching_paths`` call is therefore one of the slowest public
helpers, primarily because of its repeated tree traversal and regex filtering.

Opportunities for speedups
--------------------------

Incremental directory filtering
    ``_return_root_paths`` materialises all matches from a glob expression
    before entity filtering occurs.【F:mne_bids/path.py†L2521-L2609】  When the
    caller requests a small subset of entities (e.g., a single subject or run),
    we still scan the entire tree. Adding optional keyword arguments that allow
    early filtering (``subjects``, ``sessions``, ``runs``) inside the globbing
    step would prune large portions of the search space. For example, we could
    build the search pattern ``sub-{subjects}/*`` dynamically and skip unrelated
    directories without waiting for the regex filter.

Avoid repeated regex parsing
    The regex inside ``_filter_fnames`` is recompiled on every call and touches
    the string form of every path.【F:mne_bids/path.py†L2403-L2424】  Replacing the
    regex with entity-wise comparisons would remove the need to cast to ``str``
    and back to :class:`~pathlib.Path`. We already parse entities when creating
    :class:`~mne_bids.BIDSPath` objects, so we could reuse
    :func:`mne_bids.path.get_entities_from_fname` to extract entities once and
    then apply simple dictionary comparisons. This would trade a single regular
    expression for vectorised dictionary lookups that can early exit as soon as
    a mismatch is found.

Memoise expensive scans
    In interactive workflows users often call ``find_matching_paths`` repeatedly
    with different filters but the same root. Memoising the output of
    ``_return_root_paths`` (guarded by ``ignore_json`` and ``ignore_nosub``) in a
    ``functools.lru_cache`` keyed by ``root`` would turn repeated scans into
    constant-time lookups for subsequent calls. The cache could be exposed via an
    optional ``cache`` argument so that long-running sessions benefit without
    affecting scripts that only call the helper once.

Use ``os.scandir`` for traversal
    ``glob.iglob`` already avoids materialising the entire tree at once but we
    still pay ``Path(...).is_file()`` for every match.【F:mne_bids/path.py†L2584-L2609】
    Switching to an ``os.scandir`` based traversal can reduce both Python object
    allocations and repeated system calls. ``scandir`` returns ``DirEntry``
    objects whose ``is_file`` and ``is_dir`` checks cache stat information,
    which is especially beneficial for large datasets.

Support structured outputs
    ``find_matching_paths`` currently returns a list that must be traversed
    again whenever callers want to group by subject, session, or datatype. An
    optional ``group_by`` argument could produce a dictionary keyed by entity
    values without re-parsing the filenames. This would eliminate repeated
    ``BIDSPath`` construction in downstream code and indirectly reduce the
    number of times ``find_matching_paths`` needs to be executed.

Tighter integration with ``BIDSPath.match``
    ``BIDSPath.match`` performs entity filtering by comparing attributes on a
    ``BIDSPath`` instance. Investigating whether ``find_matching_paths`` can
    delegate to ``BIDSPath.match`` after a single tree scan (perhaps by building
    a generator of ``BIDSPath`` objects and yielding matches) would consolidate
    the two code paths and amortise parsing costs.

These suggestions are independent and can be implemented incrementally. Adopting
just the early filtering and non-regex comparisons would already reduce the
runtime by avoiding full tree scans and redundant regex work; caching and more
memory-efficient traversal would further lower the wall-clock cost in large
projects.
