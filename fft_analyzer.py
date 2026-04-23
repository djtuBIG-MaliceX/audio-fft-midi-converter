"""Constant-Q Transform frequency analysis module."""

import numpy as np
import librosa


def compute_cqt(
    audio: np.ndarray, sample_rate: int, hop_length: int = 960, n_bins: int = 84
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute Constant-Q Transform for octave-based frequency analysis.

    CQT is ideal for audio-to-MIDI conversion as it provides logarithmic
    frequency bins that map naturally to musical notes.

    Args:
        audio: Normalized audio waveform
        sample_rate: Audio sample rate in Hz
        hop_length: Samples between frames (~20ms at 48kHz = 960)
        n_bins: Number of CQT bins (84 = 7 octaves, adjust as needed)

    Returns:
        Tuple of (cqt_magnitude_array, frequencies_array)
    """
    cqt = librosa.cqt(
        y=audio,
        sr=sample_rate,
        hop_length=hop_length,
        n_bins=n_bins,
        bins_per_octave=12,
        window="hann",
        pad_mode="constant",
    )

    magnitude = np.abs(cqt)

    frequencies = librosa.cqt_frequencies(
        n_bins=n_bins, fmin=librosa.note_to_hz("C1"), bins_per_octave=12
    )

    return magnitude, frequencies


def compute_stft(
    audio: np.ndarray,
    sample_rate: int,
    n_fft: int = 2048,
    hop_length: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute Short-Time Fourier Transform as alternative to CQT.

    Args:
        audio: Normalized audio waveform
        sample_rate: Audio sample rate in Hz
        n_fft: FFT window size (default 2048)
        hop_length: Samples between frames (default n_fft/4)

    Returns:
        Tuple of (stft_magnitude_array, frequencies_array)
    """
    if hop_length is None:
        hop_length = n_fft // 4

    stft = librosa.stft(
        y=audio, n_fft=n_fft, hop_length=hop_length, window="hann", pad_mode="constant"
    )

    magnitude = np.abs(stft)

    frequencies = librosa.fft_frequencies(sr=sample_rate, n_fft=n_fft)

    return magnitude, frequencies


def hz_to_midi(frequency_hz: float) -> int:
    """Convert frequency in Hz to MIDI note number."""
    if frequency_hz <= 0:
        return 0
    return int(69 + 12 * np.log2(frequency_hz / 440.0))


def midi_to_hz(midi_note: int) -> float:
    """Convert MIDI note number to frequency in Hz."""
    if midi_note < 0:
        return 0.0
    return 440.0 * (2.0 ** ((midi_note - 69) / 12.0))


def detect_fundamental(
    magnitude_db: np.ndarray, frequencies: np.ndarray, frame_idx: int
) -> tuple[float | None, float]:
    """
    Detect the fundamental frequency (pitch) of a voice in the current frame.

    Uses a two-pass approach for speech:
    1. Direct detection: search 40-500 Hz for the strongest peak
    2. Harmonic inference: if direct detection fails or is weak, infer the
       fundamental from the spacing of strong harmonic peaks above 100 Hz.
       This handles the "missing fundamental" problem where the fundamental
       itself is very weak compared to formant harmonics.

    Args:
        magnitude_db: 2D array of shape (n_bins, n_frames) in dB scale
        frequencies: Array of frequencies corresponding to bins
        frame_idx: Current frame index

    Returns:
        Tuple of (fundamental_frequency_hz, confidence_score)
        - fundamental_frequency_hz: Detected pitch or None if not found
        - confidence_score: 0.0-1.0 based on harmonic consistency
    """
    frame_magnitude = magnitude_db[:, frame_idx]

    fmin_voice = 40.0
    fmax_voice = 500.0
    fmin_harmonics = 100.0
    fmax_harmonics = 5000.0

    freq_mask = (frequencies >= fmin_voice) & (frequencies <= fmax_voice)
    voice_bins = np.where(freq_mask)[0]

    # Pass 1: Direct detection - find strongest peak in fundamental range
    candidate_freq = None
    candidate_confidence = 0.0

    if len(voice_bins) > 0:
        voice_magnitudes = frame_magnitude[voice_bins]
        max_idx_in_voice = np.argmax(voice_magnitudes)
        candidate_freq = float(frequencies[voice_bins[max_idx_in_voice]])
        candidate_amp = float(voice_magnitudes[max_idx_in_voice])

        if candidate_amp >= -65.0:
            # Check harmonic consistency
            harmonic_consistency = 0.0
            harmonics_checked = 0

            for harmonic_num in range(2, 9):
                expected_harmonic_freq = candidate_freq * harmonic_num
                if expected_harmonic_freq > 10000.0:
                    break

                closest_bin = np.argmin(
                    np.abs(frequencies - expected_harmonic_freq)
                )
                harmonic_amp = frame_magnitude[closest_bin]

                if harmonic_amp > candidate_amp - 18.0:
                    harmonic_consistency += 1.0

                harmonics_checked += 1

            if harmonics_checked > 0:
                harmonic_consistency /= harmonics_checked

            candidate_confidence = min(1.0, 0.3 + harmonic_consistency * 0.7)

    # Pass 2: Harmonic inference - find fundamental from harmonic spacing
    # This handles speech where the fundamental is masked by strong formants
    if candidate_confidence < 0.3:
        # Find strong peaks above 100 Hz
        harmonic_mask = (frequencies >= fmin_harmonics) & (frequencies <= fmax_harmonics)
        harmonic_bins = np.where(harmonic_mask)[0]

        if len(harmonic_bins) >= 3:
            harmonic_mags = frame_magnitude[harmonic_bins]
            # Get peaks that are within 25 dB of the max in this range
            max_harm_amp = np.max(harmonic_mags)
            peak_bins = harmonic_bins[harmonic_mags > max_harm_amp - 25.0]

            if len(peak_bins) >= 3:
                peak_freqs = frequencies[peak_bins]
                peak_freqs_sorted = np.sort(peak_freqs)

                # Calculate adjacent frequency ratios
                # The fundamental is the GCD of these ratios
                best_f0 = None
                best_score = 0.0

                # Try each candidate fundamental from 30-200 Hz
                for test_f0 in np.arange(30.0, 200.0, 1.0):
                    score = 0.0
                    matches = 0

                    for harmonic_num in range(1, 10):
                        expected = test_f0 * harmonic_num
                        if expected < fmin_harmonics:
                            continue
                        if expected > fmax_harmonics:
                            break

                        closest_bin = np.argmin(
                            np.abs(frequencies - expected)
                        )
                        expected_freq = frequencies[closest_bin]
                        semitone_dist = abs(
                            12.0 * np.log2(expected_freq / expected)
                        )

                        if semitone_dist < 1.5:
                            amp = frame_magnitude[closest_bin]
                            if amp > max_harm_amp - 30.0:
                                score += 1.0
                                matches += 1

                    if matches >= 3 and score > best_score:
                        best_score = score
                        best_f0 = test_f0

                if best_f0 is not None and best_score >= 3.0:
                    # Found a consistent harmonic series
                    # Refine by averaging the inferred fundamentals from each peak pair
                    refined_f0s = []
                    for i in range(len(peak_freqs_sorted) - 1):
                        for j in range(i + 1, len(peak_freqs_sorted)):
                            ratio = peak_freqs_sorted[j] / peak_freqs_sorted[i]
                            # Check if ratio is close to an integer
                            nearest_int = round(ratio)
                            if nearest_int >= 2 and nearest_int <= 12:
                                ratio_error = abs(ratio - nearest_int)
                                if ratio_error < 0.1:
                                    inferred_f0 = peak_freqs_sorted[i] / (nearest_int - 1)
                                    if 30.0 <= inferred_f0 <= 200.0:
                                        refined_f0s.append(inferred_f0)

                    if refined_f0s:
                        candidate_freq = float(np.median(refined_f0s))
                        candidate_confidence = min(
                            1.0, 0.2 + (len(refined_f0s) * 0.1)
                        )

    if candidate_freq is None or candidate_confidence < 0.15:
        return None, 0.0

    return candidate_freq, candidate_confidence


def identify_harmonic_series(
    fundamental_hz: float,
    peaks: list[tuple[float, float, int]],
    tolerance_semitones: float = 0.5,
) -> list[dict]:
    """
    Group detected peaks into harmonic series based on a fundamental frequency.

    Each peak is checked against the expected frequencies of integer multiples
    (2x, 3x, 4x, etc.) of the fundamental. Peaks that align with a harmonic
    are assigned to that harmonic number.

    Args:
        fundamental_hz: The detected fundamental frequency in Hz
        peaks: List of (frequency_hz, amplitude_db, midi_note) tuples
        tolerance_semitones: Frequency tolerance for harmonic matching

    Returns:
        List of dicts with keys:
        - 'harmonic_number': int (1 = fundamental, 2 = first overtone, etc.)
        - 'frequency_hz': float
        - 'amplitude_db': float
        - 'midi_note': int
        - 'is_harmonic': bool (True if aligned with harmonic series)
    """
    result = []

    for freq_hz, amp_db, midi_note in peaks:
        if fundamental_hz is None or fundamental_hz <= 0:
            result.append({
                "harmonic_number": 0,
                "frequency_hz": freq_hz,
                "amplitude_db": amp_db,
                "midi_note": midi_note,
                "is_harmonic": False,
            })
            continue

        harmonic_num = freq_hz / fundamental_hz
        nearest_harmonic = round(harmonic_num)

        if nearest_harmonic < 1:
            nearest_harmonic = 1

        expected_freq = fundamental_hz * nearest_harmonic
        semitone_distance = 12.0 * np.log2(freq_hz / expected_freq)

        if abs(semitone_distance) <= tolerance_semitones:
            result.append({
                "harmonic_number": nearest_harmonic,
                "frequency_hz": freq_hz,
                "amplitude_db": amp_db,
                "midi_note": midi_note,
                "is_harmonic": True,
            })
        else:
            result.append({
                "harmonic_number": 0,
                "frequency_hz": freq_hz,
                "amplitude_db": amp_db,
                "midi_note": midi_note,
                "is_harmonic": False,
            })

    return result


def calculate_formant_strength(
    magnitude_db: np.ndarray, frequencies: np.ndarray, frame_idx: int,
    formant_center_hz: float, formant_bandwidth_hz: float = 200.0
) -> float:
    """
    Calculate the energy strength within a specific formant frequency band.

    Uses a Gaussian weighting centered on the formant center frequency to
    measure how much energy exists in that particular spectral region.

    Args:
        magnitude_db: 2D array of shape (n_bins, n_frames) in dB scale
        frequencies: Array of frequencies corresponding to bins
        frame_idx: Current frame index
        formant_center_hz: Center frequency of the formant band (e.g., F1=500Hz)
        formant_bandwidth_hz: Half-width of the formant band in Hz

    Returns:
        Normalized strength value between 0.0 and 1.0
    """
    frame_magnitude = magnitude_db[:, frame_idx]

    lower_bound = formant_center_hz - formant_bandwidth_hz
    upper_bound = formant_center_hz + formant_bandwidth_hz

    band_mask = (frequencies >= lower_bound) & (frequencies <= upper_bound)
    band_indices = np.where(band_mask)[0]

    if len(band_indices) == 0:
        return 0.0

    band_magnitudes = frame_magnitude[band_indices]
    max_band_amp = np.max(band_magnitudes)

    if max_band_amp < -60.0:
        return 0.0

    strength = min(1.0, (max_band_amp + 60.0) / 60.0)

    return strength


def find_dominant_frequencies(
    magnitude: np.ndarray,
    frequencies: np.ndarray,
    n_peaks: int = 15,
    min_db: float = -60.0,
    target_frequency_hz: float | None = None,
    bandwidth_semitones: float = 3.0,
    formant_mode: bool = False,
) -> list[dict]:
    """
    Find the dominant frequency peaks in a magnitude spectrum with formant awareness.

    In formant mode, returns structured data including fundamental frequency detection
    and harmonic series grouping. Each frame's output includes:
    - 'peaks': list of peak dicts with harmonic info
    - 'fundamental_hz': detected vocal pitch or None
    - 'formant_strengths': dict of formant band strengths

    Args:
        magnitude: 2D array of shape (n_bins, n_frames)
        frequencies: Array of frequencies corresponding to bins
        n_peaks: Maximum number of peaks to return per frame
        min_db: Minimum amplitude threshold in dB
        target_frequency_hz: Expected frequency for active tracking (optional)
        bandwidth_semitones: Frequency tolerance around target in semitones
        formant_mode: If True, include fundamental detection and harmonic grouping

    Returns:
        List of dicts per frame containing:
        - 'peaks': list of (frequency_hz, amplitude_db, midi_note) tuples
        - 'fundamental_hz': detected pitch or None (formant mode only)
        - 'harmonic_groups': grouped peak data (formant mode only)
        - 'formant_strengths': dict of formant band strengths (formant mode only)
    """
    magnitude_db = librosa.amplitude_to_db(
        magnitude, ref=np.max, amin=1e-10, top_db=-min_db
    )

    peaks_per_frame = []
    n_frames = magnitude.shape[1]

    for frame_idx in range(n_frames):
        frame_magnitude = magnitude_db[:, frame_idx]

        if target_frequency_hz is not None:
            active_threshold = min_db + 10
            valid_indices = np.where(frame_magnitude > active_threshold)[0]
        else:
            inactive_threshold = min_db + 5
            valid_indices = np.where(frame_magnitude > inactive_threshold)[0]

        if len(valid_indices) == 0:
            frame_data = {
                "peaks": [],
                "fundamental_hz": None,
                "harmonic_groups": [],
                "formant_strengths": {},
            }
            peaks_per_frame.append(frame_data)
            continue

        if target_frequency_hz is not None:
            freq_range_min = target_frequency_hz / (2 ** (bandwidth_semitones / 12))
            freq_range_max = target_frequency_hz * (2 ** (bandwidth_semitones / 12))
            valid_indices = [
                idx
                for idx in valid_indices
                if freq_range_min <= frequencies[idx] <= freq_range_max
            ]

        if len(valid_indices) == 0:
            frame_data = {
                "peaks": [],
                "fundamental_hz": None,
                "harmonic_groups": [],
                "formant_strengths": {},
            }
            peaks_per_frame.append(frame_data)
            continue

        valid_magnitudes = frame_magnitude[valid_indices]
        sorted_indices = valid_indices[np.argsort(valid_magnitudes)[::-1]]

        max_peaks = 20 if formant_mode else n_peaks
        peak_indices = sorted_indices[:max_peaks]

        frame_peaks = []
        for idx in peak_indices:
            freq_hz = float(frequencies[idx])
            amp_db = float(frame_magnitude[idx])
            midi_note = hz_to_midi(freq_hz)
            frame_peaks.append((freq_hz, amp_db, midi_note))

        frame_data = {
            "peaks": frame_peaks,
            "fundamental_hz": None,
            "harmonic_groups": [],
            "formant_strengths": {},
        }

        if formant_mode:
            fundamental_hz, confidence = detect_fundamental(
                magnitude_db, frequencies, frame_idx
            )
            frame_data["fundamental_hz"] = fundamental_hz

            if fundamental_hz is not None and len(frame_peaks) > 0:
                harmonic_groups = identify_harmonic_series(
                    fundamental_hz, frame_peaks, tolerance_semitones=0.5
                )
                frame_data["harmonic_groups"] = harmonic_groups

            formant_centers = {
                "F1": 500.0,
                "F2": 1500.0,
                "F3": 3500.0,
                "F4": 7500.0,
            }
            formant_bandwidths = {
                "F1": 200.0,
                "F2": 500.0,
                "F3": 1000.0,
                "F4": 3500.0,
            }

            formant_strengths = {}
            for formant_name, center in formant_centers.items():
                strength = calculate_formant_strength(
                    magnitude_db, frequencies, frame_idx, center,
                    formant_bandwidths[formant_name]
                )
                formant_strengths[formant_name] = strength

            frame_data["formant_strengths"] = formant_strengths

        peaks_per_frame.append(frame_data)

    return peaks_per_frame
