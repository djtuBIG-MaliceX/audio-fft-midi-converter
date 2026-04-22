import sys
sys.path.insert(0, '.')

import numpy as np
import librosa
from fft_analyzer import compute_cqt, find_dominant_frequencies
from channel_mapper import ChannelMapper

# Load audio
audio, sr = librosa.load('15bandsinetest.wav', sr=None)
frame_duration = 1.0 / 50
hop_length = int(sr * frame_duration)

magnitude, frequencies = compute_cqt(audio, sr, hop_length=hop_length, n_bins=112)
peaks = find_dominant_frequencies(magnitude, frequencies, n_peaks=15)

mapper = ChannelMapper(n_channels=15, exclude_channel=10)

print("Frame 0 analysis:")
print(f"Peaks found: {len(peaks[0])}")
for i, (freq, amp, note) in enumerate(peaks[0]):
    # Check which band this frequency would fall into
    ch_min, ch_max = 65.4, 3136.0
    band_width = (ch_max - ch_min) / 15
    band = int((freq - ch_min) / band_width)
    print(f"  Peak {i}: {freq:>8.2f} Hz -> MIDI {note:3d} (band {band})")

print("\nChannel frequency ranges:")
for i, ch in enumerate(mapper.channels):
    min_f, max_f = mapper.get_frequency_range_for_channel(i)
    print(f"  Channel {ch.channel:2d}: {min_f:>7.1f} - {max_f:>8.1f} Hz")
