import numpy as np
import librosa

audio, sr = librosa.load('15bandsinetest.wav', sr=None)
frame_duration = 1.0 / 50
hop_length = int(sr * frame_duration)

magnitude, frequencies = librosa.cqt(audio, sr=sr, hop_length=hop_length, n_bins=112)
frame_mag = magnitude[:, 0]

# Find top peaks without local maxima filter
top_n = 15
top_indices = np.argsort(frame_mag)[-top_n:][::-1]

print(f"Top {top_n} peaks by amplitude:")
for idx in top_indices:
    freq = frequencies[idx]
    amp = frame_mag[idx]
    midi_note = int(69 + 12 * np.log2(freq / 440.0))
    print(f"  Bin {idx:3d}: {freq:>7.2f} Hz -> MIDI {midi_note:3d}, amp={amp:>6.1f}")

# Check expected notes
expected = [36, 48, 55, 59, 60, 64, 67, 72, 79, 83, 88, 95, 96, 100, 103]
print("\nExpected MIDI notes in top peaks:")
for expected_note in expected:
    expected_freq = 440.0 * (2.0 ** ((expected_note - 69) / 12.0))
    closest_idx = np.argmin(np.abs(frequencies - expected_freq))
    if closest_idx in top_indices:
        print(f"  MIDI {expected_note:3d} IS in top peaks")
    else:
        print(f"  MIDI {expected_note:3d} NOT in top peaks (bin {closest_idx}, amp={frame_mag[closest_idx]:.1f})")
