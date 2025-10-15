Performance Notes
=================

Find matching paths
-------------------

``find_matching_paths`` recursively enumerates candidate files via
:func:`~mne_bids.path._return_root_paths`, filters these candidates with
:func:`~mne_bids.path._filter_fnames`, and finally instantiates
:class:`~mne_bids.BIDSPath` objects for each surviving filename. The filtering
stage had to rebuild an identical regular expression every time the function was
called, even if users repeatedly queried the same combination of entities. On
large datasets this meant that the pure-Python overhead of building and compiling
the regular expression rivalled the time needed to traverse the filesystem.

To reduce this overhead we now cache the compiled regular expression that encodes
entity constraints. Reusing the cached matcher avoids repeated calls to
``re.compile`` and lets the filtering loop use the already-compiled regular
expression directly. Combined with using :func:`os.fspath` to avoid temporary
``Path`` objects during matching, the hot path inside
``find_matching_paths`` allocates fewer intermediate objects and spends more time
doing the actual filtering work.

Opportunities for further optimisation
--------------------------------------

The profiling data you supplied highlighted that ``find_matching_paths`` is among
the slowest public helpers in :mod:`mne_bids.path`. The following ideas outline
additional avenues for improvement:

* Skip disk ``stat`` calls during discovery by filtering purely on path strings.
  ``_return_root_paths`` currently relies on :meth:`pathlib.Path.is_file` which
  performs system calls for every candidate path.
* Collapse the two-step ``_return_root_paths`` → ``_filter_fnames`` process by
  streaming filenames through a generator. This would allow us to stop iterating
  once a caller requests only the first few matches and to avoid materialising
  all intermediate results in memory.
* Pre-index entity combinations at import time for static datasets. When users
  repeatedly query the same BIDS root, a memoized index (for example stored as a
  ``dict`` mapping entity tuples to path lists) can provide instant lookups at
  the cost of extra memory.
* Parse entity values with a lightweight splitter instead of a large regular
  expression. Replacing the regex with a custom parser would avoid the overhead
  of the regex engine and could unlock richer filtering operations.

These optimisations are intentionally independent so they can be adopted in
isolation. Each proposal should be accompanied by targeted benchmarks to verify
that improvements hold for representative datasets of different sizes.
