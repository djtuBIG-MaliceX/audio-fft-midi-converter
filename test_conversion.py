#!/usr/bin/env python3
"""Test script to verify audio-to-MIDI conversion with synthetic audio."""

import numpy as np
from pathlib import Path


def generate_test_audio(
    output_path: str, duration: float = 5.0, sample_rate: int = 44100
):
    """Generate a test audio file with varying frequencies and volumes."""

    t = np.linspace(0, duration, int(duration * sample_rate), False)

    # Create a complex signal with multiple frequency components that change over time
    audio = np.zeros_like(t)

    # Segment 1: Low frequency fundamental (C3 = 130.81 Hz)
    segment1_end = duration * 0.25
    t1 = t[t < segment1_end]
    audio[t < segment1_end] += 0.3 * np.sin(2 * np.pi * 130.81 * t1)

    # Add harmonics
    for harmonic in [2, 3, 4]:
        audio[t < segment1_end] += (
            0.15 / harmonic * np.sin(2 * np.pi * 130.81 * harmonic * t1)
        )

    # Segment 2: Frequency glide (pitch bend test) - C3 to G4
    segment2_start = duration * 0.25
    segment2_end = duration * 0.5
    t2 = t[(t >= segment2_start) & (t < segment2_end)]
    if len(t2) > 0:
        # Linear frequency glide from 130.81 Hz to 392.00 Hz
        freq_glide = np.linspace(130.81, 392.00, len(t2))
        phase = np.cumsum(2 * np.pi * freq_glide / sample_rate)
        audio[(t >= segment2_start) & (t < segment2_end)] += 0.3 * np.sin(phase)

    # Segment 3: Sudden frequency jump (new note trigger test) - C5
    segment3_start = duration * 0.5
    segment3_end = duration * 0.75
    t3 = t[(t >= segment3_start) & (t < segment3_end)]
    if len(t3) > 0:
        audio[(t >= segment3_start) & (t < segment3_end)] += 0.4 * np.sin(
            2 * np.pi * 523.25 * t3
        )

    # Segment 4: Volume spike test (+6dB threshold) - E4 with sudden volume increase
    segment4_start = duration * 0.75
    t4 = t[t >= segment4_start]
    if len(t4) > 0:
        # First half quiet, second half loud (volume jump)
        mid_idx = len(t4) // 2
        audio[t >= segment4_start][:mid_idx] += 0.15 * np.sin(
            2 * np.pi * 329.63 * t4[:mid_idx]
        )
        audio[t >= segment4_start][mid_idx:] += 0.3 * np.sin(
            2 * np.pi * 329.63 * t4[mid_idx:]
        )

    # Normalize
    audio = audio / np.max(np.abs(audio)) * 0.9

    # Save as WAV
    import soundfile as sf

    sf.write(output_path, audio, sample_rate)
    print(f"Generated test audio: {output_path} ({duration}s @ {sample_rate}Hz)")


def main():
    """Run the complete test."""
    test_dir = Path(__file__).parent

    # Generate test audio
    test_audio = test_dir / "test_audio.wav"
    generate_test_audio(str(test_audio), duration=5.0)

    # Convert to MIDI
    output_midi = test_dir / "test_output.mid"

    print("\nConverting to MIDI...")
    from audio_to_midi import main as midi_main

    # Simulate command-line arguments
    import sys

    original_argv = sys.argv.copy()
    try:
        sys.argv = [
            "audio_to_midi.py",
            str(test_audio),
            "-o",
            str(output_midi),
            "--formant-mode",
        ]
        midi_main()
    finally:
        sys.argv = original_argv

    # Verify output
    if output_midi.exists():
        print(f"\n✓ Test passed! MIDI file created: {output_midi}")

        # Show basic info about the MIDI file
        import mido

        mid = mido.MidiFile(str(output_midi))
        print(f"  Type: {mid.type}")
        print(f"  Ticks per beat: {mid.ticks_per_beat}")
        print(f"  Tracks: {len(mid.tracks)}")

        total_messages = sum(len(track) for track in mid.tracks)
        print(f"  Total messages: {total_messages}")
    else:
        print("\n✗ Test failed! MIDI file not created.")
        return 1

    # Cleanup
    test_audio.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    exit(main())
