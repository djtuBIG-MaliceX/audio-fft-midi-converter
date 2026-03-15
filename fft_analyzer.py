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

    return peaks_per_frame
