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

        # Find local maxima (peaks higher than neighbors)
        peak_indices = []
        for i in range(1, len(frame_magnitude) - 1):
            # Check if this bin is a local maximum (higher than both neighbors)
            if frame_magnitude[i] > frame_magnitude[i-1] and frame_magnitude[i] > frame_magnitude[i+1]:
                # Also check if above threshold
                if frame_magnitude[i] > min_db + 20:
                    peak_indices.append(i)

        # Also check endpoints
        if len(frame_magnitude) > 0 and frame_magnitude[0] > min_db + 20:
            if len(frame_magnitude) == 1 or frame_magnitude[0] > frame_magnitude[1]:
                peak_indices.insert(0, 0)
        if len(frame_magnitude) > 1 and frame_magnitude[-1] > min_db + 20:
            if frame_magnitude[-1] > frame_magnitude[-2]:
                peak_indices.append(len(frame_magnitude) - 1)

        if len(peak_indices) == 0:
            peaks_per_frame.append([])
            continue

        # Sort by amplitude and get top n_peaks
        sorted_indices = sorted(peak_indices, key=lambda idx: frame_magnitude[idx], reverse=True)
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

        # Find peaks above threshold
        valid_indices = np.where(frame_magnitude > min_db + 20)[0]

        if len(valid_indices) == 0:
            peaks_per_frame.append([])
            continue

        # Sort by amplitude ( loudest first)
        sorted_indices = valid_indices[np.argsort(frame_magnitude[valid_indices])[::-1]]
        
        # Get top peaks, but filter to keep only local maxima
        # This prevents harmonics/spurious peaks from dominating
        peak_indices = []
        for idx in sorted_indices:
            # Check if this is a local maximum (or near the edge)
            is_local_max = False
            if idx == 0:
                is_local_max = frame_magnitude[idx] > frame_magnitude[idx + 1]
            elif idx == len(frame_magnitude) - 1:
                is_local_max = frame_magnitude[idx] > frame_magnitude[idx - 1]
            else:
                is_local_max = (frame_magnitude[idx] > frame_magnitude[idx - 1] and 
                               frame_magnitude[idx] > frame_magnitude[idx + 1])
            
            if is_local_max:
                peak_indices.append(idx)
                
                # Stop when we have enough peaks
                if len(peak_indices) >= n_peaks:
                    break

        frame_peaks = []
        for idx in peak_indices:
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
    print("Fixed with filtered local maxima detection")
else:
    print("Old function not found")
