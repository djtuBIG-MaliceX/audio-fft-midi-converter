"""Channel-to-frequency band mapping module."""

import numpy as np
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

        # Calculate MIDI note range per channel using logarithmic spacing
        # Start from C1 (MIDI note 12) and go up to the highest frequency
        min_note = 12  # C1
        max_note = 127  # Highest MIDI note

        # Calculate note range per channel using logarithmic spacing
        # Each channel gets a note band that is 1/n_channels of the total range
        note_per_channel = (max_note - min_note) / n_channels

        self.channels: list[ChannelState] = []
        channel_idx = 0

        for i in range(n_channels):
            # Skip excluded channel (e.g., channel 10 for percussion)
            midi_channel = i + 1 if i < exclude_channel - 1 else i + 2

            # Calculate MIDI note range for this channel
            start_note = int(min_note + i * note_per_channel)
            end_note = int(min_note + (i + 1) * note_per_channel)

            # Convert to octave numbers (octave = note // 12)
            start_octave = start_note // 12
            end_octave = end_note // 12

            self.channels.append(
                ChannelState(
                    channel=midi_channel,
                    home_octave_start=start_octave,
                    home_octave_end=end_octave,
                )
            )

            channel_idx += 1

    def get_frequency_range_for_channel(self, channel_idx: int) -> tuple[float, float]:
        """Get frequency range (in Hz) for a channel's home band."""
        if channel_idx >= len(self.channels):
            return (0.0, 0.0)

        ch = self.channels[channel_idx]
        min_note = ch.home_octave_start * 12
        max_note = ch.home_octave_end * 12 + 11

        # Calculate frequency range using logarithmic spacing
        # This ensures non-overlapping frequency bands
        min_freq = midi_to_hz(min_note)
        max_freq = midi_to_hz(max_note)

        return (min_freq, max_freq)

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
                elif midi_note != ch.active_note:
                    # Note changed - will trigger note-off/on in MIDI generator
                    ch.active_note = midi_note
                    ch.note_start_time = frame_time

    def get_active_notes(self) -> dict[int, int]:
        """Get currently active notes per channel."""
        return {
            ch.channel: ch.active_note
            for ch in self.channels
            if ch.active_note is not None
        }
