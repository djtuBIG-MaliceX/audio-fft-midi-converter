import re

with open('fft_analyzer.py', 'r') as f:
    content = f.read()

old_func = '''def find_dominant_frequencies(
    magnitude: np.ndarray,
    frequencies: np.ndarray,
    n_peaks: int = 15,
    min_db: float = -60.0,
) -> list[list[tuple[float, float, int]]]:
    """
    Find the dominant frequency peaks in a magnitude spectrum.

    Args:
        magnitude: 2D array of shape (n_bins, n_frames)
        frequencies: Array of frequencies corresponding to bins
        n_peaks: Maximum number of peaks to return per frame
        min_db: Minimum amplitude threshold in dB

    Returns:
        List of tuples (frequency_hz, amplitude_db, midi_note) for each peak
    """
    # Convert magnitude to dB
    magnitude_db = librosa.amplitude_to_db(
        magnitude, ref=np.max, amin=1e-10, top_db=-min_db
    )

    peaks_per_frame = []
    n_frames = magnitude.shape[1]

    for frame_idx in range(n_frames):
        frame_magnitude = magnitude_db[:, frame_idx]

        # Find peaks above threshold
        valid_indices = np.where(frame_magnitude > min_db + 20)[0]  # Within 20dB of max

        if len(valid_indices) == 0:
            peaks_per_frame.append([])
            continue

        # Sort by amplitude and get top n_peaks
        sorted_indices = valid_indices[np.argsort(frame_magnitude[valid_indices])[::-1]]
        top_indices = sorted_indices[:n_peaks]

        frame_peaks = []
        for idx in top_indices:
            freq_hz = float(frequencies[idx])
            amp_db = float(frame_magnitude[idx])
            midi_note = hz_to_midi(freq_hz)
            frame_peaks.append((freq_hz, amp_db, midi_note))

        peaks_per_frame.append(frame_peaks)

    return peaks_per_frame'''

new_func = '''def find_dominant_frequencies(
    magnitude: np.ndarray,
    frequencies: np.ndarray,
    n_peaks: int = 15,
    min_db: float = -60.0,
) -> list[list[tuple[float, float, int]]]:
    """
    Find the dominant frequency peaks in a magnitude spectrum.

    Args:
        magnitude: 2D array of shape (n_bins, n_frames)
        frequencies: Array of frequencies corresponding to bins
        n_peaks: Maximum number of peaks to return per frame
        min_db: Minimum amplitude threshold in dB

    Returns:
        List of tuples (frequency_hz, amplitude_db, midi_note) for each peak
    """
    # Convert magnitude to dB
    magnitude_db = librosa.amplitude_to_db(
        magnitude, ref=np.max, amin=1e-10, top_db=-min_db
    )

    peaks_per_frame = []
    n_frames = magnitude.shape[1]

    for frame_idx in range(n_frames):
        frame_magnitude = magnitude_db[:, frame_idx]

        # Find local maxima (peaks that are higher than neighbors)
        peak_indices = []
        for i in range(1, len(frame_magnitude) - 1):
            # Check if this bin is a local maximum
            if frame_magnitude[i] > frame_magnitude[i-1] and frame_magnitude[i] > frame_magnitude[i+1]:
                # Also check if above threshold (within 20dB of max)
                if frame_magnitude[i] > min_db + 20:
                    peak_indices.append(i)

        if len(peak_indices) == 0:
            peaks_per_frame.append([])
            continue

        # Sort peaks by amplitude
        sorted_peaks = sorted(peak_indices, key=lambda idx: frame_magnitude[idx], reverse=True)
        top_indices = sorted_peaks[:n_peaks]

        frame_peaks = []
        for idx in top_indices:
            freq_hz = float(frequencies[idx])
            amp_db = float(frame_magnitude[idx])
            midi_note = hz_to_midi(freq_hz)
            frame_peaks.append((freq_hz, amp_db, midi_note))

        peaks_per_frame.append(frame_peaks)

    return peaks_per_frame'''

if old_func in content:
    content = content.replace(old_func, new_func)
    with open('fft_analyzer.py', 'w') as f:
        f.write(content)
    print("Fixed find_dominant_frequencies function")
else:
    print("Could not find exact match - checking for variations")
