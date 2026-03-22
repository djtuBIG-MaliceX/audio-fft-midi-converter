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
    # Compute CQT with specified hop length
    cqt = librosa.cqt(
        y=audio,
        sr=sample_rate,
        hop_length=hop_length,
        n_bins=n_bins,
        bins_per_octave=12,
        window="hann",
        pad_mode="constant",
    )

    # Convert to magnitude (absolute value)
    magnitude = np.abs(cqt)

    # Get corresponding frequencies for each bin
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

    # Compute STFT
    stft = librosa.stft(
        y=audio, n_fft=n_fft, hop_length=hop_length, window="hann", pad_mode="constant"
    )

    # Convert to magnitude (absolute value)
    magnitude = np.abs(stft)

    # Get corresponding frequencies for each bin
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


def find_dominant_frequencies(
    magnitude: np.ndarray,
    frequencies: np.ndarray,
    n_peaks: int = 15,
    min_db: float = -60.0,
    target_frequency_hz: float | None = None,
    bandwidth_semitones: float = 3.0,
    formant_mode: bool = False,
) -> list[list[tuple[float, float, int]]]:
    """
    Find the dominant frequency peaks in a magnitude spectrum.

    Args:
        magnitude: 2D array of shape (n_bins, n_frames)
        frequencies: Array of frequencies corresponding to bins
        n_peaks: Maximum number of peaks to return per frame
        min_db: Minimum amplitude threshold in dB
        target_frequency_hz: Expected frequency for active tracking (optional)
        bandwidth_semitones: Frequency tolerance around target in semitones
        formant_mode: If True, return up to 3 peaks per channel for formant preservation

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

        # Determine threshold based on whether we have a target frequency
        if target_frequency_hz is not None:
            # Active tracking: use tighter threshold (-50dB = min_db + 10)
            active_threshold = min_db + 10
            valid_indices = np.where(frame_magnitude > active_threshold)[0]
        else:
            # Inactive: use looser threshold (-55dB = min_db + 5)
            inactive_threshold = min_db + 5
            valid_indices = np.where(frame_magnitude > inactive_threshold)[0]

        if len(valid_indices) == 0:
            peaks_per_frame.append([])
            continue

        # Filter by bandwidth if target frequency is specified
        if target_frequency_hz is not None:
            freq_range_min = target_frequency_hz / (2 ** (bandwidth_semitones / 12))
            freq_range_max = target_frequency_hz * (2 ** (bandwidth_semitones / 12))
            valid_indices = [
                idx
                for idx in valid_indices
                if freq_range_min <= frequencies[idx] <= freq_range_max
            ]

        if len(valid_indices) == 0:
            peaks_per_frame.append([])
            continue

        # Calculate exact frequency for centroid refinement
        valid_magnitudes = frame_magnitude[valid_indices]

        # Sort by amplitude (loudest first)
        sorted_indices = valid_indices[np.argsort(valid_magnitudes)[::-1]]

        # Determine how many peaks to return
        max_peaks = 3 if formant_mode else n_peaks

        # Get top peaks (no local maxima filtering for better formant capture)
        peak_indices = sorted_indices[:max_peaks]

        frame_peaks = []
        for idx in peak_indices:
            freq_hz = float(frequencies[idx])
            amp_db = float(frame_magnitude[idx])
            midi_note = hz_to_midi(freq_hz)
            frame_peaks.append((freq_hz, amp_db, midi_note))

        peaks_per_frame.append(frame_peaks)

    return peaks_per_frame
