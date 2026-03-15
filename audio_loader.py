"""Audio file loading and preprocessing module."""

import numpy as np
import soundfile as sf
from pathlib import Path


def load_audio(
    filepath: str, target_sample_rate: int | None = None
) -> tuple[np.ndarray, int]:
    """
    Load audio file and return normalized waveform with sample rate.

    Args:
        filepath: Path to audio file (WAV, MP3, FLAC, AIFF supported)
        target_sample_rate: Optional resampling target (None = keep original)

    Returns:
        Tuple of (normalized_audio_array, sample_rate)
    """
    path = Path(filepath)

    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")

    # Load audio using soundfile (librosa backend also works)
    import librosa

    y, sr = librosa.load(str(filepath), sr=None, mono=True)

    # Normalize to prevent clipping (-1 to 1 range)
    if np.max(np.abs(y)) > 0:
        y = y / np.max(np.abs(y)) * 0.95

    # Resample if target specified
    if target_sample_rate is not None and sr != target_sample_rate:
        y = librosa.resample(y, orig_sr=sr, target_sr=target_sample_rate)
        sr = int(target_sample_rate)

    return y, int(sr)


def get_audio_duration(samples: int, sample_rate: int) -> float:
    """Calculate audio duration in seconds."""
    return samples / sample_rate
