"""Shared code for the EEG preprocessing teaching notebooks.

It lives in `public/` because marimo's browser export copies that folder but doesn't bundle
local modules: each notebook fetches this file and loads it at startup (see `bootstrap` in any
notebook). Everything here uses NumPy, SciPy and matplotlib only, so it runs in the browser.

The data file holds the recording before the ICA, with stage 4's provisional reference. Every
cleaning step is a matrix product, so a module can apply any combination of them cheaply:

- removing ICA component k subtracts `patterns[:, k] * source_k(t)` from every channel;
- the average reference subtracts the mean over the good channels at each sample;
- a filter acts on each channel over time, so it commutes with both.
"""
import io
import sys

import numpy as np
from scipy import signal

BEFORE = "#9aa0a6"   # grey: the recording before the step being taught
AFTER = "#1a73e8"    # blue: after it
POSTERIOR = ("O1", "O2", "Oz", "POz", "PO3", "PO4", "Pz", "P1", "P2")


async def load(mo, name):
    """Read a data file from `public/`, in the browser or on disk."""
    path = mo.notebook_location() / "public" / name
    if sys.platform == "emscripten":
        from pyodide.http import pyfetch
        response = await pyfetch(str(path))
        source = io.BytesIO(await response.bytes())
    else:
        source = path
    with np.load(source) as archive:
        return {key: archive[key] for key in archive.files}


def image_url(mo, name):
    """Where a file in `public/` is served from, for mo.image."""
    return str(mo.notebook_location() / "public" / name)


class Recording:
    """The retrieval recording and the decisions needed to clean it."""

    def __init__(self, arrays, kernels):
        self.arrays = arrays
        self.kernels = kernels
        self.sfreq = float(arrays["sfreq"])
        self.channels = [str(c) for c in arrays["ch_names"]]
        self.bad = [str(c) for c in arrays["bad_channels"]]
        self.good = [c for c in self.channels if c not in self.bad]
        self.run_starts = arrays["run_starts"]
        self.run_lengths = arrays["run_lengths"]
        self.clean_cues = arrays["cues"][~arrays["rejected"]]
        self.ica_exclude = [int(k) for k in arrays["ica_exclude"]]
        self.patterns = arrays["ica_patterns"]
        self._good_rows = [self.channels.index(c) for c in self.good]
        self._average = None
        self._sources = {}

    def rows(self, names):
        return [self.channels.index(name) for name in names]

    def raw(self, names):
        """Channels in µV, before the ICA, as float32."""
        rows = self.rows(names)
        return self.arrays["data"][rows].astype(np.float32) * self.arrays["scale"][rows, None]

    def _matmul(self, weights):
        """weights (k x channels) @ the full recording, in chunks to keep memory low."""
        data, scale = self.arrays["data"], self.arrays["scale"]
        w = (weights * scale[None, :]).astype(np.float32)
        out = np.empty((w.shape[0], data.shape[1]), np.float32)
        step = 20000
        for i in range(0, data.shape[1], step):
            out[:, i:i + step] = w @ data[:, i:i + step].astype(np.float32)
        return out

    def average(self):
        """Mean over the good channels at each sample: the average reference."""
        if self._average is None:
            w = np.zeros((1, len(self.channels)), np.float32)
            w[0, self._good_rows] = 1 / len(self._good_rows)
            self._average = self._matmul(w)[0]
        return self._average

    def sources(self, comps):
        """ICA component time courses (components x samples)."""
        missing = [k for k in comps if k not in self._sources]
        if missing:
            out = self._matmul(self.arrays["ica_unmix"][missing])
            out -= self.arrays["ica_offset"][missing, None]
            self._sources.update(zip(missing, out))
        return np.stack([self._sources[k] for k in comps]) if comps else None

    def referenced(self, names):
        """Channels before the ICA, average-referenced over the good channels."""
        return self.raw(names) - self.average()[None, :]

    def ref_patterns(self, names, comps):
        """Component scalp patterns for these channels, average-referenced like the data."""
        p = self.patterns[:, comps]
        return p[self.rows(names)] - p[self._good_rows].mean(axis=0, keepdims=True)

    def unreferenced(self, names, remove=None):
        """Channels after the reviewed ICA (or `remove`), before the average reference.

        For a module that sets its own reference, such as one where channels are dropped.
        """
        remove = self.ica_exclude if remove is None else list(remove)
        x = self.raw(names)
        if remove:
            x -= self.patterns[self.rows(names)][:, remove] @ self.sources(remove)
        return x

    def cleaned(self, names, remove=None):
        """Channels after the reviewed ICA (or `remove`), average-referenced."""
        remove = self.ica_exclude if remove is None else list(remove)
        x = self.referenced(names)
        if remove:
            x -= self.ref_patterns(names, remove) @ self.sources(remove)
        return x

    def kernel(self, high_pass, low_pass):
        return self.kernels[f"hp{high_pass}_lp{low_pass}"]

    def filter(self, x, kernels):
        """Zero-phase FIR filtering, run by run, with each run's ends padded by reflection."""
        if not isinstance(kernels, (list, tuple)):
            kernels = [kernels]
        for kernel in kernels:
            pad = len(kernel) // 2
            out = np.empty_like(x)
            for start, length in zip(self.run_starts, self.run_lengths):
                run = np.pad(x[:, start:start + length], ((0, 0), (pad, pad)), mode="reflect")
                out[:, start:start + length] = signal.oaconvolve(
                    run, kernel[None, :], mode="valid", axes=1)
            x = out
        return x

    def epochs(self, x, cues, tmin=-0.5, tmax=1.0, baseline=(-0.2, 0.0)):
        """Baseline-corrected single trials (trials x samples) of a 1-D signal."""
        offsets = np.arange(int(round(tmin * self.sfreq)), int(round(tmax * self.sfreq)) + 1)
        trials = x[cues[:, None] + offsets[None, :]]
        base = (offsets >= baseline[0] * self.sfreq) & (offsets < baseline[1] * self.sfreq)
        return offsets / self.sfreq, trials - trials[:, base].mean(axis=1, keepdims=True)

    def complete(self, cues, tmin=-0.5, tmax=1.0):
        """Which cues have a whole epoch inside their run (the last may not: the recording
        can stop soon after it)."""
        run = np.searchsorted(self.run_starts, cues, side="right") - 1
        start, end = self.run_starts[run], self.run_starts[run] + self.run_lengths[run]
        return (cues + tmin * self.sfreq >= start) & (cues + tmax * self.sfreq < end)

    def erp(self, x, tmin=-0.5, tmax=1.0, baseline=(-0.2, 0.0)):
        """Baseline-corrected average over the clean trials of a 1-D signal."""
        time, trials = self.epochs(x, self.clean_cues, tmin, tmax, baseline)
        return time, trials.mean(axis=0)


def figure_html(mo, plt, fig):
    """Render a figure for marimo and free it, so long sessions don't pile up figures."""
    fig.tight_layout()
    html = mo.as_html(fig)
    plt.close(fig)
    return html


def plot_traces(plt, time, names, before, after, ylabel_suffix=" (µV)", height=1.4):
    """One row per channel: the recording before (grey) and after (blue) a step."""
    fig, axes = plt.subplots(len(names), 1, figsize=(7, height * len(names)), sharex=True,
                             squeeze=False)
    for ax, name, b, a in zip(axes[:, 0], names, before, after):
        ax.plot(time, b - b.mean(), color=BEFORE, lw=0.7)
        ax.plot(time, a - a.mean(), color=AFTER, lw=1.4)
        ax.set_ylabel(f"{name}{ylabel_suffix}")
    return fig, axes[:, 0]


def plot_erp(plt, time, before, after, ylabel="Back of the head (µV)",
             labels=("Before", "After")):
    fig, ax = plt.subplots(figsize=(7, 2.8))
    ax.axhline(0, color="k", lw=0.5)
    ax.axvline(0, color="k", ls="--", lw=0.6)
    ax.axvspan(-0.2, 0, color="#f1f3f4", zorder=0, label="Baseline period")
    ax.plot(time, before, color=BEFORE, lw=1.5, label=labels[0])
    ax.plot(time, after, color=AFTER, lw=1.2, label=labels[1])
    ax.set(xlabel="Time from the object appearing (s)", ylabel=ylabel,
           xlim=(time[0], time[-1]))
    ax.legend(frameon=False, loc="upper left", fontsize=8)
    return fig, ax


def plot_spectrum(plt, freqs, before, after, fmax=60, labels=("Before", "After"),
                  ylabel="Power (µV²/Hz)"):
    fig, ax = plt.subplots(figsize=(7, 2.8))
    keep = (freqs > 0) & (freqs <= fmax)
    ax.semilogy(freqs[keep], before[keep], color=BEFORE, lw=1.5, label=labels[0])
    ax.semilogy(freqs[keep], after[keep], color=AFTER, lw=1.2, label=labels[1])
    ax.set(xlabel="Frequency (Hz)", ylabel=ylabel, xlim=(0, fmax),
           xticks=range(0, fmax + 1, 10))
    ax.legend(frameon=False, loc="upper right")
    return fig, ax
