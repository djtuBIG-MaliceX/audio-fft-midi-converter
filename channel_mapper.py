"""Channel-to-frequency band mapping module."""

import numpy as np
import math
from dataclasses import dataclass, field

from fft_analyzer import hz_to_midi, midi_to_hz


@dataclass
class ChannelState:
    """Track state for a single MIDI channel."""

    channel: int
    home_octave_start: int
    home_octave_end: int
    active_note: int | None = None
    last_frequency_hz: float | None = None
    target_frequency_hz: float | None = None
    last_volume_db: float = -float("inf")
    note_start_time: float = 0.0
    note_stable_frames: int = 0
    freq_range_hz: tuple[float, float] = (0.0, 0.0)
    is_warmup: bool = True
    note_on_threshold: float = -40.0
    note_off_threshold: float = -49.0


class ChannelMapper:
    """
    Map frequency bands to MIDI channels using hybrid selection approach.

    Each channel has a "home" octave band but can grab louder peaks from
    other octaves if they exceed the +6dB threshold.
    Supports overlapping bands for better formant capture and state-aware
    tracking with hysteresis volume triggers.
    """

    def __init__(
        self,
        n_channels: int = 15,
        exclude_channel: int = 10,
        overlap_percent: float = 33.0,
    ):
        """
        Initialize channel mapper.

        Args:
            n_channels: Number of frequency-tracking channels (default 15)
            exclude_channel: Channel to exclude from frequency tracking (10 = percussion)
            overlap_percent: Percentage of overlap between adjacent channels (default 33%)
        """
        self.n_channels = n_channels
        self.exclude_channel = exclude_channel
        self.overlap_percent = overlap_percent

        fmin = 65.4
        fmax = 3136.0

        log_fmin = math.log(fmin)
        log_fmax = math.log(fmax)
        log_range = log_fmax - log_fmin

        self.channels: list[ChannelState] = []
        channel_idx = 0

        for i in range(n_channels):
            midi_channel = i + 1 if i < exclude_channel - 1 else i + 2

            log_min_freq = log_fmin + i * (log_range / n_channels)
            log_max_freq = log_fmin + (i + 1) * (log_range / n_channels)

            base_min_freq = math.exp(log_min_freq)
            base_max_freq = math.exp(log_max_freq)

            overlap_factor = 1.0 + (overlap_percent / 100.0) / 2.0

            if i == 0:
                min_freq = base_min_freq
                max_freq = base_max_freq * overlap_factor
            elif i == n_channels - 1:
                min_freq = base_min_freq / overlap_factor
                max_freq = base_max_freq
            else:
                min_freq = base_min_freq / overlap_factor
                max_freq = base_max_freq * overlap_factor

            min_note = hz_to_midi(min_freq)
            max_note = hz_to_midi(max_freq)

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

        self.frame_count = 0

    def get_frequency_range_for_channel(self, channel_idx: int) -> tuple[float, float]:
        """Get frequency range (in Hz) for a channel's home band."""
        if channel_idx >= len(self.channels):
            return (0.0, 0.0)

        ch = self.channels[channel_idx]
        
        return ch.freq_range_hz

    def get_channel_for_frequency(self, freq_hz: float) -> list[int]:
        """
        Get all channels that could potentially track a given frequency.
        
        Args:
            freq_hz: Frequency in Hz
            
        Returns:
            List of channel numbers that cover this frequency
        """
        channels_for_freq = []
        
        for ch_idx, channel in enumerate(self.channels):
            min_freq, max_freq = self.get_frequency_range_for_channel(ch_idx)
            
            if min_freq <= freq_hz <= max_freq:
                channels_for_freq.append(channel.channel)
        
        return channels_for_freq

    def calculate_assignment_score(
        self,
        freq_hz: float,
        amp_db: float,
        channel_idx: int,
        target_frequency_hz: float | None = None,
    ) -> tuple[float, bool]:
        """
        Calculate assignment score for a peak to a channel.
        
        For active channels (with target frequency), prefer proximity to target.
        For inactive channels, prefer louder amplitude.
        
        Args:
            freq_hz: Frequency of the peak
            amp_db: Amplitude of the peak in dB
            channel_idx: Index of the channel being scored
            target_frequency_hz: Expected frequency for active tracking (optional)
            
        Returns:
            Tuple of (score, should_prefer_this_channel)
            - score: Higher is better
            - should_prefer_this_channel: True if this is the best match for active tracking
        """
        min_freq, max_freq = self.get_frequency_range_for_channel(channel_idx)
        
        if not (min_freq <= freq_hz <= max_freq):
            return (-float("inf"), False)
        
        center_freq = (min_freq + max_freq) / 2
        
        if target_frequency_hz is not None:
            freq_distance = abs(freq_hz - target_frequency_hz)
            
            score = -freq_distance
            
            center_distance = abs(freq_hz - center_freq)
            score -= center_distance * 0.1
            
            should_prefer = freq_distance < abs(center_freq - target_frequency_hz)
            
            return (score, should_prefer)
        else:
            score = amp_db
            
            freq_distance = abs(freq_hz - center_freq)
            max_distance = (max_freq - min_freq) / 2
            if max_distance > 0:
                edge_penalty = (freq_distance / max_distance) * 5
                score -= edge_penalty
            
            return (score, True)

    def assign_bands_to_channels(
        self,
        peaks_per_frame: list[tuple[float, float, int]],
        frame_time: float,
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

        sorted_peaks = sorted(peaks_per_frame, key=lambda x: x[0])

        for ch_idx, channel in enumerate(self.channels):
            min_freq, max_freq = self.get_frequency_range_for_channel(ch_idx)
            channel_state = self.channels[ch_idx]

            target_freq = None
            if channel_state.active_note is not None:
                target_freq = midi_to_hz(channel_state.active_note)

            best_peak: tuple[float, float, int] | None = None
            best_score: float = -float("inf")

            for freq_hz, amp_db, midi_note in sorted_peaks:
                score, _ = self.calculate_assignment_score(
                    freq_hz, amp_db, ch_idx, target_freq
                )

                if score > best_score:
                    best_score = score
                    best_peak = (freq_hz, amp_db, midi_note)

            assignments[channel.channel] = best_peak

        return assignments

    def update_channel_states(
        self, assignments: dict[int, tuple[float, float, int] | None], frame_time: float
    ):
        """Update internal channel states based on current assignments."""
        self.frame_count += 1
        warmup_frames = 3

        for ch_idx, channel in enumerate(self.channels):
            peak = assignments.get(channel.channel)

            if peak is not None:
                freq_hz, amp_db, midi_note = peak

                channel.last_frequency_hz = freq_hz
                channel.last_volume_db = amp_db

                if self.frame_count <= warmup_frames:
                    channel.is_warmup = True
                    
                    if channel.target_frequency_hz is None:
                        channel.target_frequency_hz = freq_hz
                    
                    continue
                
                channel.is_warmup = False

                if channel.active_note is None:
                    note_on_threshold = channel.note_on_threshold
                    if amp_db > note_on_threshold:
                        channel.active_note = midi_note
                        channel.note_start_time = frame_time
                        channel.target_frequency_hz = freq_hz
                        channel.note_stable_frames = 1
                else:
                    if midi_note != channel.active_note:
                        volume_diff = amp_db - channel.last_volume_db
                        
                        if volume_diff >= 9.0:
                            channel.active_note = midi_note
                            channel.target_frequency_hz = freq_hz
                            channel.note_start_time = frame_time
                            channel.note_stable_frames = 1
                        else:
                            if channel.target_frequency_hz is not None:
                                current_distance = abs(freq_hz - channel.target_frequency_hz)
                                prev_freq = channel.last_frequency_hz or 0
                                prev_distance = abs(prev_freq - channel.target_frequency_hz)
                                
                                if current_distance < prev_distance:
                                    channel.active_note = midi_note
                                    channel.target_frequency_hz = freq_hz
                            else:
                                channel.active_note = midi_note
                                channel.target_frequency_hz = freq_hz
        
                    if midi_note == channel.active_note:
                        channel.note_stable_frames += 1
                        
                        if channel.target_frequency_hz is not None:
                            alpha = 0.3
                            channel.target_frequency_hz = (
                                alpha * freq_hz + (1 - alpha) * channel.target_frequency_hz
                            )
            else:
                # No peak assigned
                if channel.active_note is not None:
                    last_vol = channel.last_volume_db
                    
                    # Note-off if volume dropped 9dB or less than note-off threshold
                    if (
                        last_vol < channel.note_off_threshold
                        or (last_vol - amp_db) >= 9.0 if 'amp_db' in locals() else last_vol < -30
                    ):
                        channel.active_note = None
                        channel.target_frequency_hz = None
                
                channel.note_stable_frames = 0

    def get_active_notes(self) -> dict[int, int]:
        """Get currently active notes per channel."""
        return {
            ch.channel: ch.active_note
            for ch in self.channels
            if ch.active_note is not None
        }

    def reset_frame_count(self):
        """Reset frame counter for warm-up."""
        self.frame_count = 0
