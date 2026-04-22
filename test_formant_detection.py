#!/usr/bin/env python3
"""Test formant-preserving audio-to-MIDI conversion with synthetic speech-like audio."""

import numpy as np
from pathlib import Path
import librosa


def generate_vowel_audio(
    output_path: str, duration: float = 6.0, sample_rate: int = 44100
):
    """Generate synthetic speech-like audio with vowel formants.

    Creates a signal that simulates a male voice saying "ah" then transitioning
    to "ee", with proper fundamental frequency and formant structure.

    Args:
        output_path: Path to save the WAV file
        duration: Duration in seconds
        sample_rate: Sample rate in Hz
    """
    t = np.linspace(0, duration, int(duration * sample_rate), False)

    audio = np.zeros_like(t)

    # Male voice fundamental: 150 Hz
    f0 = 150.0

    # "ah" vowel: F1=500Hz, F2=1500Hz, F3=2500Hz
    # "ee" vowel: F1=300Hz, F2=2300Hz, F3=3000Hz

    # Segment 1: "ah" vowel (0-2.5s)
    seg1_end = duration * 0.42
    mask1 = t < seg1_end
    if np.any(mask1):
        t1 = t[mask1]
        # Fundamental with harmonics
        phase = 2 * np.pi * f0 * t1 / sample_rate
        fundamental = np.sin(phase)

        # Formant filtering: amplify specific harmonic bands
        formants_ah = [
            (500.0, 1.8),   # F1 strong
            (1500.0, 1.4),  # F2 moderate
            (2500.0, 1.0),  # F3 weaker
        ]

        for formant_freq, strength in formants_ah:
            # Create bandpass around each formant by adding harmonics near that frequency
            harmonic_num = round(formant_freq / f0)
            if harmonic_num >= 2:
                for h in [harmonic_num - 1, harmonic_num, harmonic_num + 1]:
                    if h >= 2:
                        amp = strength / h * 0.15
                        audio[mask1] += amp * np.sin(2 * np.pi * h * f0 * t1 / sample_rate)

        audio[mask1] += 0.25 * fundamental

    # Segment 2: Transition (2.5-3.5s)
    seg2_start = duration * 0.42
    seg2_end = duration * 0.58
    mask2 = (t >= seg2_start) & (t < seg2_end)
    if np.any(mask2):
        t2 = t[mask2]
        f0_seg = np.linspace(150.0, 180.0, len(t2))

        phase = np.cumsum(2 * np.pi * f0_seg / sample_rate)
        fundamental = np.sin(phase)

        for h in range(2, 10):
            freq_harm = f0_seg * h
            amp = 0.12 / h
            audio[mask2] += amp * np.sin(2 * np.pi * freq_harm * t2 / sample_rate)

        audio[mask2] += 0.25 * fundamental

    # Segment 3: "ee" vowel (3.5-5s)
    seg3_start = duration * 0.58
    seg3_end = duration * 0.83
    mask3 = (t >= seg3_start) & (t < seg3_end)
    if np.any(mask3):
        t3 = t[mask3]
        phase = 2 * np.pi * 180.0 * t3 / sample_rate
        fundamental = np.sin(phase)

        formants_ee = [
            (300.0, 1.5),   # F1 lower for "ee"
            (2300.0, 1.6),  # F2 higher for "ee"
            (3000.0, 1.0),  # F3
        ]

        for formant_freq, strength in formants_ee:
            harmonic_num = round(formant_freq / 180.0)
            for h in [max(2, harmonic_num - 1), harmonic_num, min(harmonic_num + 1, 20)]:
                amp = strength / h * 0.14
                audio[mask3] += amp * np.sin(2 * np.pi * h * 180.0 * t3 / sample_rate)

        audio[mask3] += 0.25 * fundamental

    # Segment 4: Fade out (5-6s)
    seg4_start = duration * 0.83
    mask4 = t >= seg4_start
    if np.any(mask4):
        fade = 1.0 - (t[mask4] - seg4_start) / (duration - seg4_start)
        audio[mask4] *= fade

    # Normalize
    if np.max(np.abs(audio)) > 0:
        audio = audio / np.max(np.abs(audio)) * 0.9

    import soundfile as sf
    sf.write(output_path, audio, sample_rate)
    print(f"Generated vowel test audio: {output_path} ({duration}s @ {sample_rate}Hz)")


def generate_pitch_glide_audio(
    output_path: str, duration: float = 5.0, sample_rate: int = 44100
):
    """Generate audio with pitch glide to test smooth transitions.

    Creates a signal that glides from C3 (130.81 Hz) to G4 (392 Hz) while
    maintaining formant structure, testing pitch bend behavior.

    Args:
        output_path: Path to save the WAV file
        duration: Duration in seconds
        sample_rate: Sample rate in Hz
    """
    t = np.linspace(0, duration, int(duration * sample_rate), False)

    audio = np.zeros_like(t)

    # Glide fundamental from 130.81 to 392 Hz
    f0_start = 130.81
    f0_end = 392.0

    phase = np.cumsum(2 * np.pi * np.linspace(f0_start, f0_end, len(t)) / sample_rate)
    fundamental = np.sin(phase)

    # Add formant harmonics that track with the glide
    for harmonic in range(2, 10):
        freq = np.linspace(f0_start * harmonic, f0_end * harmonic, len(t))
        amp = 0.1 / harmonic
        h_phase = np.cumsum(2 * np.pi * freq / sample_rate)
        audio += amp * np.sin(h_phase)

    # Normalize
    if np.max(np.abs(audio)) > 0:
        audio = audio / np.max(np.abs(audio)) * 0.9

    import soundfile as sf
    sf.write(output_path, audio, sample_rate)
    print(f"Generated pitch glide test audio: {output_path} ({duration}s @ {sample_rate}Hz)")


def test_formant_detection():
    """Test the formant detection and harmonic grouping functions."""
    print("\n" + "=" * 60)
    print("Testing Formant Detection Functions")
    print("=" * 60)

    from fft_analyzer import (
        compute_cqt,
        find_dominant_frequencies,
        detect_fundamental,
        identify_harmonic_series,
        calculate_formant_strength,
    )

    sample_rate = 44100
    duration = 2.0
    f0 = 150.0

    t = np.linspace(0, duration, int(duration * sample_rate), False)

    # Create stronger vocal-like signal with emphasis on fundamental
    audio = np.zeros_like(t)
    
    # Strong fundamental
    audio += 0.5 * np.sin(2 * np.pi * f0 * t / sample_rate)
    
    # Add harmonics with decreasing amplitude
    for h in range(2, 12):
        audio += 0.2 / h * np.sin(2 * np.pi * f0 * h * t / sample_rate)
    
    # Add slight amplitude modulation to simulate vocal tract
    am_mod = 1.0 + 0.3 * np.sin(2 * np.pi * 5 * t)
    audio *= am_mod

    audio = audio / np.max(np.abs(audio)) * 0.9

    hop_length = int(sample_rate * 0.02)
    magnitude, frequencies = compute_cqt(audio, sample_rate, hop_length=hop_length, n_bins=84)

    magnitude_db = librosa.amplitude_to_db(magnitude, ref=np.max, amin=1e-10)

    print(f"\nTesting fundamental detection on {duration}s of audio...")
    expected_midi = int(69 + 12 * np.log2(f0 / 440.0))
    print(f"Expected fundamental: {f0} Hz (MIDI note ~{expected_midi})")

    n_frames = magnitude.shape[1]
    detected_count = 0
    for frame_idx in range(min(20, n_frames)):
        fund_hz, confidence = detect_fundamental(magnitude_db, frequencies, frame_idx)
        if fund_hz is not None:
            detected_count += 1
            semitone_error = abs(12 * np.log2(fund_hz / f0))
            print(f"  Frame {frame_idx:3d}: detected {fund_hz:.1f} Hz (confidence={confidence:.2f}, error={semitone_error:.3f} st)")

    print(f"\nDetected fundamental in {detected_count}/{min(20, n_frames)} frames")

    print("\nTesting harmonic series grouping...")
    peaks_data = find_dominant_frequencies(magnitude, frequencies, n_peaks=20, formant_mode=True)
    first_frame = peaks_data[0]

    print(f"  Peaks found: {len(first_frame['peaks'])}")
    print(f"  Fundamental detected: {first_frame['fundamental_hz']}")

    if first_frame['harmonic_groups']:
        print("  Harmonic groups:")
        for hg in first_frame['harmonic_groups'][:10]:
            status = "HARMONIC" if hg['is_harmonic'] else "non-harm"
            print(f"    MIDI {hg['midi_note']:3d}: {hg['frequency_hz']:7.1f} Hz, amp={hg['amplitude_db']:.1f} dB, h#{hg['harmonic_number']} [{status}]")

    print("\nTesting formant strength calculation...")
    for formant_name in ['F1', 'F2', 'F3']:
        strength = first_frame['formant_strengths'].get(formant_name, 0.0)
        print(f"  {formant_name} strength: {strength:.3f}")

    return detected_count > 0


def test_full_conversion():
    """Test the full audio-to-MIDI conversion pipeline."""
    print("\n" + "=" * 60)
    print("Testing Full Conversion Pipeline")
    print("=" * 60)

    test_dir = Path(__file__).parent

    # Generate vowel audio
    vowel_audio = test_dir / "vowel_test.wav"
    generate_vowel_audio(str(vowel_audio), duration=6.0)

    # Convert to MIDI
    output_midi = test_dir / "vowel_output.mid"

    print("\nConverting vowel audio to MIDI...")
    from audio_to_midi import main as midi_main

    import sys
    original_argv = sys.argv.copy()
    try:
        sys.argv = [
            "audio_to_midi.py",
            str(vowel_audio),
            "-o", str(output_midi),
            "--formant-mode",
            "--stability-threshold", "3",
        ]
        midi_main()
    finally:
        sys.argv = original_argv

    if output_midi.exists():
        import mido
        mid = mido.MidiFile(str(output_midi))

        print(f"\nMIDI file analysis:")
        print(f"  Type: {mid.type}")
        print(f"  Tracks: {len(mid.tracks)}")

        total_messages = sum(len(track) for track in mid.tracks)
        print(f"  Total messages: {total_messages}")

        # Count event types per track
        note_on_count = 0
        note_off_count = 0
        pitch_bend_count = 0

        for track in mid.tracks:
            for msg in track:
                if msg.type == 'note_on' and msg.velocity > 0:
                    note_on_count += 1
                elif msg.type == 'note_off':
                    note_off_count += 1
                elif msg.type == 'pitchwheel':
                    pitch_bend_count += 1

        print(f"\nEvent breakdown:")
        print(f"  Note-on events: {note_on_count}")
        print(f"  Note-off events: {note_off_count}")
        print(f"  Pitch bend events: {pitch_bend_count}")

        # Check for excessive pitch bending
        if note_on_count > 0:
            pb_ratio = pitch_bend_count / max(note_on_count, 1)
            print(f"\n  Pitch bend ratio: {pb_ratio:.2f} per note-on")
            if pb_ratio < 5.0:
                print("  ✓ Good: pitch bend usage is reasonable")
            else:
                print("  ⚠ Warning: high pitch bend ratio may indicate warbling")

        print(f"\n✓ Conversion successful! MIDI file: {output_midi}")
    else:
        print("\n✗ Conversion failed!")
        return 1

    # Cleanup
    vowel_audio.unlink(missing_ok=True)

    return 0


def test_pitch_glide():
    """Test pitch glide conversion."""
    print("\n" + "=" * 60)
    print("Testing Pitch Glide Conversion")
    print("=" * 60)

    test_dir = Path(__file__).parent

    glide_audio = test_dir / "glide_test.wav"
    generate_pitch_glide_audio(str(glide_audio), duration=5.0)

    output_midi = test_dir / "glide_output.mid"

    print("\nConverting pitch glide audio to MIDI...")
    from audio_to_midi import main as midi_main

    import sys
    original_argv = sys.argv.copy()
    try:
        sys.argv = [
            "audio_to_midi.py",
            str(glide_audio),
            "-o", str(output_midi),
        ]
        midi_main()
    finally:
        sys.argv = original_argv

    if output_midi.exists():
        import mido
        mid = mido.MidiFile(str(output_midi))

        print(f"\nMIDI file analysis:")
        print(f"  Tracks: {len(mid.tracks)}")

        note_on_count = sum(1 for track in mid.tracks for msg in track if msg.type == 'note_on' and msg.velocity > 0)
        pitch_bend_count = sum(1 for track in mid.tracks for msg in track if msg.type == 'pitchwheel')

        print(f"  Note-on events: {note_on_count}")
        print(f"  Pitch bend events: {pitch_bend_count}")

        if note_on_count > 0:
            pb_ratio = pitch_bend_count / max(note_on_count, 1)
            print(f"  Pitch bend ratio: {pb_ratio:.2f} per note-on")

        print(f"\n✓ Glide conversion successful!")
    else:
        print("\n✗ Glide conversion failed!")
        return 1

    glide_audio.unlink(missing_ok=True)
    return 0


def main():
    """Run all formant detection tests."""
    import librosa

    print("=" * 60)
    print("FORMANT-PRESERVING AUDIO-TO-MIDI TEST SUITE")
    print("=" * 60)

    results = []

    # Test 1: Formant detection functions
    try:
        success = test_formant_detection()
        results.append(("Formant Detection", success))
    except Exception as e:
        print(f"\n✗ Formant detection test failed with error: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Formant Detection", False))

    # Test 2: Full conversion with vowel audio
    try:
        success = test_full_conversion() == 0
        results.append(("Vowel Conversion", success))
    except Exception as e:
        print(f"\n✗ Vowel conversion test failed with error: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Vowel Conversion", False))

    # Test 3: Pitch glide conversion
    try:
        success = test_pitch_glide() == 0
        results.append(("Pitch Glide Conversion", success))
    except Exception as e:
        print(f"\n✗ Pitch glide test failed with error: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Pitch Glide Conversion", False))

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    all_passed = True
    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {test_name}")
        if not passed:
            all_passed = False

    print("=" * 60)
    if all_passed:
        print("All tests passed!")
        return 0
    else:
        print("Some tests failed.")
        return 1


if __name__ == "__main__":
    exit(main())
