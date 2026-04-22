import sys
sys.path.insert(0, '.')

import numpy as np
import librosa
from fft_analyzer import compute_cqt

audio, sr = librosa.load('15bandsinetest.wav', sr=None)
frame_duration = 1.0 / 50
hop_length = int(sr * frame_duration)

magnitude, frequencies = compute_cqt(audio, sr, hop_length=hop_length, n_bins=112)

# Expected MIDI notes from reference
expected_midi = [36, 48, 55, 59, 60, 64, 67, 72, 79, 83, 88, 95, 96, 100, 103]

frame_mag_db = librosa.amplitude_to_db(magnitude[:, 0], ref=np.max)
max_amp = np.max(frame_mag_db)

print("All expected notes with their amplitudes:")
for midi_note in expected_midi:
    freq = 440.0 * (2.0 ** ((midi_note - 69) / 12.0))
    closest_idx = np.argmin(np.abs(frequencies - freq))
    
    amp_db = frame_mag_db[closest_idx]
    ratio_to_max = 10 ** ((amp_db - max_amp) / 20)
    
    print(f"  MIDI {midi_note:3d}: amp={amp_db:>6.1f} dB, ratio to max={ratio_to_max:.3f}")
    
    # Check if this bin would be detected as a local maximum
    # (need to check neighbors in CQT magnitude)
    if closest_idx > 0 and closest_idx < len(frame_mag_db) - 1:
        left = frame_mag_db[closest_idx - 1]
        right = frame_mag_db[closest_idx + 1]
        is_local_max = amp_db > left and amp_db > right
        print(f"    Neighbors: {left:.1f}, {amp_db:.1f}, {right:.1f} -> local max: {is_local_max}")
