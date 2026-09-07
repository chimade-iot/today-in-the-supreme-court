#!/usr/bin/env python3
"""
Synthesise the news bed and stings for Today in the Supreme Court.

Everything here is generated from first principles with numpy, so the
resulting audio is original to this project. There is no third-party
music licence to track and nothing to attribute.

Outputs (into assets/):
    bed.wav    - seamless loopable underscore, ~32s
    intro.wav  - opening sting
    outro.wav  - closing sting
"""
import numpy as np
import soundfile as sf
from pathlib import Path

SR = 44100
ASSETS = Path(__file__).parent / "assets"

# A minor. Frequencies in Hz.
A1, A2, C3, E3, A3, C4, E4, G4, A4, B4, C5, E5 = (
    55.00, 110.00, 130.81, 164.81, 220.00,
    261.63, 329.63, 392.00, 440.00, 493.88, 523.25, 659.25,
)


def env(n, attack, decay, sustain_level=0.0, release=None):
    """Simple AD/ADSR-ish envelope over n samples (times in seconds)."""
    a = max(1, int(attack * SR))
    d = max(1, int(decay * SR))
    out = np.zeros(n)
    a = min(a, n)
    out[:a] = np.linspace(0, 1, a)
    rest = n - a
    if rest > 0:
        d = min(d, rest)
        out[a:a + d] = np.linspace(1, sustain_level, d)
        if rest - d > 0:
            out[a + d:] = sustain_level
    return out


def tone(freq, dur, kind="sine", detune=0.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = freq * (1 + detune)
    if kind == "sine":
        w = np.sin(2 * np.pi * f * t)
    elif kind == "tri":
        w = 2 * np.abs(2 * ((f * t) % 1) - 1) - 1
    elif kind == "saw":
        w = 2 * ((f * t) % 1) - 1
    else:
        raise ValueError(kind)
    return w


def add(buf, sig, at):
    """Mix sig into buf at sample offset `at`, growing nothing."""
    i = int(at)
    j = min(len(buf), i + len(sig))
    if i >= len(buf):
        return
    buf[i:j] += sig[: j - i]


def soft_clip(x, ceiling=0.95):
    return ceiling * np.tanh(x / max(ceiling, 1e-9))


def onepole_lowpass(x, cutoff):
    """Cheap one-pole LPF, cutoff in Hz."""
    dt = 1.0 / SR
    rc = 1.0 / (2 * np.pi * cutoff)
    alpha = dt / (rc + dt)
    y = np.zeros_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += alpha * (x[i] - acc)
        y[i] = acc
    return y


def make_bed(bars=16, bpm=100):
    """A restrained news underscore: drone, pulse, sparse arpeggio, ticks."""
    beat = 60.0 / bpm
    bar = beat * 4
    total = bar * bars
    n = int(total * SR)
    buf = np.zeros(n)
    t = np.arange(n) / SR

    # --- Low drone: two slightly detuned saws through a moving lowpass -----
    drone = 0.0
    for det in (-0.004, 0.0, 0.004):
        drone = drone + tone(A1, total, "saw", det) * 0.33
    # slow filter sweep via amplitude-shaped harmonics (cheap but effective)
    sweep = 0.5 + 0.5 * np.sin(2 * np.pi * t / (total / 2))
    drone = drone * (0.35 + 0.25 * sweep)
    drone = onepole_lowpass(drone, 220)
    add(buf, drone * 0.5, 0)

    # A quiet fifth above, breathing on a different cycle
    fifth = tone(E3, total, "tri") * (0.06 + 0.04 * np.sin(2 * np.pi * t / (total / 3)))
    add(buf, onepole_lowpass(fifth, 900), 0)

    # --- Eighth-note bass pulse -------------------------------------------
    pulse_dur = beat * 0.42
    pn = int(pulse_dur * SR)
    for k in range(int(total / (beat / 2))):
        at = k * (beat / 2) * SR
        if at + pn > n:
            break
        # accent the downbeat of each bar
        strong = (k % 8) == 0
        amp = 0.16 if strong else 0.075
        p = tone(A2, pulse_dur, "tri") * env(pn, 0.004, pulse_dur * 0.9) * amp
        add(buf, p, at)

    # --- Sparse arpeggio: A minor 7 shape, one note per beat, ducking in ---
    arp_notes = [A4, C5, E5, G4, A4, E4, C4, E4]
    note_dur = beat * 0.9
    nn = int(note_dur * SR)
    for k in range(int(total / beat)):
        # leave space: play only on beats 1 and 3 of each bar
        if k % 4 not in (0, 2):
            continue
        at = k * beat * SR
        if at + nn > n:
            break
        f = arp_notes[k % len(arp_notes)]
        v = (tone(f, note_dur, "sine") * 0.7 + tone(f * 2, note_dur, "sine") * 0.15)
        v = v * env(nn, 0.012, note_dur * 0.85) * 0.055
        add(buf, v, at)

    # --- Beat ticks: filtered noise, very quiet, newsroom clock feel -------
    rng = np.random.default_rng(7)
    tick_dur = 0.035
    tn = int(tick_dur * SR)
    for k in range(int(total / beat)):
        at = k * beat * SR
        if at + tn > n:
            break
        noise = rng.normal(0, 1, tn)
        noise = onepole_lowpass(noise, 3200)
        noise = noise * env(tn, 0.001, tick_dur) * (0.030 if k % 4 == 0 else 0.016)
        add(buf, noise, at)

    # --- Make it loop seamlessly: crossfade tail into head -----------------
    xf = int(bar * SR)  # one bar crossfade
    head = buf[:xf].copy()
    tail = buf[-xf:].copy()
    ramp = np.linspace(0, 1, xf)
    buf[:xf] = head * ramp + tail * (1 - ramp)
    buf = buf[:-xf]

    return soft_clip(buf * 0.85)


def make_intro():
    """Opening sting: rising fifth, a struck chord, settle onto the tonic."""
    dur = 3.4
    n = int(dur * SR)
    buf = np.zeros(n)
    rng = np.random.default_rng(3)

    # low swell
    swell = tone(A2, dur, "saw") * 0.25
    swell = onepole_lowpass(swell, 400) * env(n, 1.6, 1.8, 0.15)
    add(buf, swell, 0)

    # three ascending stabs
    for i, f in enumerate((A3, C4, E4)):
        at = (0.30 + i * 0.30) * SR
        d = 0.85
        sn = int(d * SR)
        v = (tone(f, d, "tri") * 0.6 + tone(f * 2, d, "sine") * 0.2)
        v = v * env(sn, 0.006, d * 0.9) * 0.20
        add(buf, v, at)

    # the arrival chord at ~1.5s
    at = 1.45 * SR
    d = 1.9
    cn = int(d * SR)
    chord = np.zeros(cn)
    for f, g in ((A3, 0.5), (C4, 0.38), (E4, 0.34), (A4, 0.28), (E5, 0.16)):
        chord += tone(f, d, "sine") * g
    chord = chord * env(cn, 0.010, d * 0.95) * 0.16
    add(buf, chord, at)

    # a short noise sweep into the arrival
    sw = int(1.45 * SR)
    noise = rng.normal(0, 1, sw)
    noise = onepole_lowpass(noise, 5000) * np.linspace(0, 1, sw) ** 3 * 0.05
    add(buf, noise, 0)

    return soft_clip(buf)


def make_outro():
    """Closing: the same chord, resolving down and fading out."""
    dur = 3.0
    n = int(dur * SR)
    buf = np.zeros(n)
    for f, g in ((A2, 0.45), (A3, 0.34), (C4, 0.24), (E4, 0.20)):
        buf += tone(f, dur, "sine") * g
    buf *= env(n, 0.02, dur * 0.98) * 0.20
    return soft_clip(buf)


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    print("synthesising bed ...")
    sf.write(ASSETS / "bed.wav", make_bed(), SR)
    print("synthesising intro ...")
    sf.write(ASSETS / "intro.wav", make_intro(), SR)
    print("synthesising outro ...")
    sf.write(ASSETS / "outro.wav", make_outro(), SR)
    for f in ("bed.wav", "intro.wav", "outro.wav"):
        print(f"  {f}: {(ASSETS / f).stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
