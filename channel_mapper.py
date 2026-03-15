"""Channel-to-frequency band mapping module."""

import numpy as np
import math
from dataclasses import dataclass, field

from fft_analyzer import hz_to_midi, midi_to_hz


@dataclass
class ChannelState:
    """Track state for a single MIDI channel."""

    channel: int
    home_octave_start: int  # Starting octave for this channel's primary band
    home_octave_end: int  # Ending octave for this channel's primary band
    active_note: int | None = None  # Currently playing MIDI note
    last_frequency_hz: float | None = None
    last_volume_db: float = -float("inf")
    note_start_time: float = 0.0
    note_stable_frames: int = 0  # Number of consecutive frames with same note detection
    freq_range_hz: tuple[float, float] = (
        0.0,
        0.0,
    )  # Actual frequency range for this channel


class ChannelMapper:
    """
    Map frequency bands to MIDI channels using hybrid selection approach.

    Each channel has a "home" octave band but can grab louder peaks from
    other octaves if they exceed the +6dB threshold.
    """

    def __init__(self, n_channels: int = 15, exclude_channel: int = 10):
        """
        Initialize channel mapper.

        Args:
            n_channels: Number of frequency-tracking channels (default 15)
            exclude_channel: Channel to exclude from frequency tracking (10 = percussion)
        """
        self.n_channels = n_channels
        self.exclude_channel = exclude_channel

        # Calculate frequency range per channel using logarithmic spacing
        # Start from C2 (65 Hz) to cover typical piano range up to E8 (3136 Hz)
        fmin = 65.4  # C2
        fmax = 3136.0  # E8 (adjusted to fit the 15 notes in reference)

        # Calculate logarithmic frequency bands using exponential spacing
        # This ensures more even coverage across the frequency spectrum
        log_fmin = math.log(fmin)
        log_fmax = math.log(fmax)
        log_range = log_fmax - log_fmin

        self.channels: list[ChannelState] = []
        channel_idx = 0

        for i in range(n_channels):
            # Skip excluded channel (e.g., channel 10 for percussion)
            midi_channel = i + 1 if i < exclude_channel - 1 else i + 2

            # Calculate logarithmic frequency range for this channel
            log_min_freq = log_fmin + i * (log_range / n_channels)
            log_max_freq = log_fmin + (i + 1) * (log_range / n_channels)

            min_freq = math.exp(log_min_freq)
            max_freq = math.exp(log_max_freq)

            # Convert frequency range to MIDI note range
            min_note = hz_to_midi(min_freq)
            max_note = hz_to_midi(max_freq)

            # Convert to octave numbers (octave = note // 12)
            start_octave = min_note // 12
            end_octave = max_note // 12

            self.channels.append(
                ChannelState(
                    channel=midi_channel,
                    home_octave_start=start_octave,
                    home_octave_end=end_octave,
                    freq_range_hz=(min_freq, max_freq),
                )
            )

            channel_idx += 1

    def get_frequency_range_for_channel(self, channel_idx: int) -> tuple[float, float]:
        """Get frequency range (in Hz) for a channel's home band."""
        if channel_idx >= len(self.channels):
            return (0.0, 0.0)

        ch = self.channels[channel_idx]
        
        # Return the stored frequency range
        return ch.freq_range_hz

    def assign_bands_to_channels(
        self, peaks_per_frame: list[tuple[float, float, int]], frame_time: float
    ) -> dict[int, tuple[float, float, int] | None]:
        """
        Assign frequency peaks to channels using systematic frequency band mapping.

        Args:
            peaks_per_frame: List of (freq_hz, amplitude_db, midi_note) tuples for this frame
            frame_time: Current time in seconds

        Returns:
            Dict mapping channel number to assigned peak or None
        """
        assignments: dict[int, tuple[float, float, int] | None] = {}

        # Sort peaks by frequency (lowest to highest) to ensure systematic mapping
        sorted_peaks = sorted(peaks_per_frame, key=lambda x: x[0])

        # Assign peaks to channels in frequency order
        for ch_idx, channel in enumerate(self.channels):
            # Calculate frequency range for this channel
            min_freq, max_freq = self.get_frequency_range_for_channel(ch_idx)

            # Find the best peak in this channel's frequency range
            best_peak: tuple[float, float, int] | None = None
            best_score: float = -float("inf")

            for freq_hz, amp_db, midi_note in sorted_peaks:
                # Check if frequency falls within this channel's range
                if min_freq <= freq_hz <= max_freq:
                    # Score based on amplitude (louder peaks get priority)
                    score = amp_db

                    # Bonus for being closer to the center of the frequency range
                    center_freq = (min_freq + max_freq) / 2
                    freq_distance = abs(freq_hz - center_freq)
                    score -= freq_distance * 0.1  # Small penalty for edge frequencies

                    if score > best_score:
                        best_score = score
                        best_peak = (freq_hz, amp_db, midi_note)

            assignments[channel.channel] = best_peak

        return assignments

    def update_channel_states(
        self, assignments: dict[int, tuple[float, float, int] | None], frame_time: float
    ):
        """Update internal channel states based on current assignments."""
        for ch in self.channels:
            peak = assignments.get(ch.channel)

            if peak is not None:
                freq_hz, amp_db, midi_note = peak

                # Update state
                ch.last_frequency_hz = freq_hz
                ch.last_volume_db = amp_db

                if ch.active_note is None:
                    ch.active_note = midi_note
                    ch.note_start_time = frame_time
                    ch.note_stable_frames = 1
                elif midi_note != ch.active_note:
                    # Note changed - increment stability counter before switching
                    ch.note_stable_frames += 1
                    # Only switch note if stable for 3 consecutive frames (prevents rapid flutter)
                    if ch.note_stable_frames >= 3:
                        ch.active_note = midi_note
                        ch.note_start_time = frame_time
                else:
                    # Same note detected - reset stability counter
                    ch.note_stable_frames = 1
            else:
                # No peak assigned - reset stability counter
                ch.note_stable_frames = 0

    def get_active_notes(self) -> dict[int, int]:
        """Get currently active notes per channel."""
        return {
            ch.channel: ch.active_note
            for ch in self.channels
            if ch.active_note is not None
        }
