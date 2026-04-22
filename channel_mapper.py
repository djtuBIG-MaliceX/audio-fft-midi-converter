"""Channel-to-frequency band mapping module with formant awareness."""

import numpy as np
import math
from dataclasses import dataclass, field

from fft_analyzer import hz_to_midi, midi_to_hz


@dataclass
class ChannelState:
    """Track state for a single MIDI channel with formant awareness."""

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

    # Formant tracking fields
    harmonic_series: list[int] = field(default_factory=list)
    fundamental_reference_hz: float | None = None
    formant_stability_count: int = 0
    is_formant_stable: bool = False
    last_harmonic_number: int = 0


class ChannelMapper:
    """
    Map frequency peaks to MIDI channels using formant-aware assignment.

    Channels 1-3: Low fundamentals (80-350 Hz) - Vocal pitch tracking
    Channels 4-6: F1 formant range (350-1500 Hz) - First formant + harmonics
    Channels 7-10: F2/F3 formant range (1500-5000 Hz) - Second/third formants
    Channels 11-14: Upper harmonics/air (5000-11000 Hz) - Sibilants, consonants, brightness
    Channel 15: Ultra-high (>11000 Hz) - Air, transients

    Supports harmonic series tracking, formant stability detection, and
    priority-based assignment that prefers harmonically-related peaks.
    """

    def __init__(
        self,
        n_channels: int = 15,
        exclude_channel: int = 10,
        overlap_percent: float = 33.0,
        stability_threshold: int = 5,
        band_definitions: list[tuple[float, float]] | None = None,
    ):
        """
        Initialize channel mapper.

        Args:
            n_channels: Number of frequency-tracking channels (default 15)
            exclude_channel: Channel to exclude from frequency tracking (10 = percussion)
            overlap_percent: Percentage of overlap between adjacent channels (default 33%)
            stability_threshold: Frames needed before entering formant stable mode
            band_definitions: Optional list of (min_freq, max_freq) tuples for custom bands
        """
        self.n_channels = n_channels
        self.exclude_channel = exclude_channel
        self.overlap_percent = overlap_percent
        self.stability_threshold = stability_threshold

        if band_definitions is not None:
            self.band_definitions = band_definitions
        else:
            self.band_definitions = [
                (80.0, 150.0),
                (150.0, 250.0),
                (250.0, 350.0),
                (350.0, 600.0),
                (600.0, 1000.0),
                (1000.0, 1500.0),
                (1500.0, 2200.0),
                (2200.0, 3000.0),
                (3000.0, 4000.0),
                (4000.0, 5000.0),
                (5000.0, 6500.0),
                (6500.0, 8000.0),
                (8000.0, 9500.0),
                (9500.0, 11000.0),
                (11000.0, 14000.0),
            ]

        self.channels: list[ChannelState] = []
        channel_idx = 0

        for i in range(n_channels):
            midi_channel = i + 1 if i < exclude_channel - 1 else i + 2

            if i < len(self.band_definitions):
                min_freq, max_freq = self.band_definitions[i]
            else:
                log_fmin = math.log(65.4)
                log_fmax = math.log(14000.0)
                log_range = log_fmax - log_fmin
                log_min_freq = log_fmin + i * (log_range / n_channels)
                log_max_freq = log_fmin + (i + 1) * (log_range / n_channels)
                min_freq = math.exp(log_min_freq)
                max_freq = math.exp(log_max_freq)

            overlap_factor = 1.0 + (overlap_percent / 100.0) / 2.0

            if i == 0:
                min_freq = min_freq
                max_freq = max_freq * overlap_factor
            elif i == n_channels - 1:
                min_freq = min_freq / overlap_factor
                max_freq = max_freq
            else:
                min_freq = min_freq / overlap_factor
                max_freq = max_freq * overlap_factor

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

    def _get_channel_index(self, channel_number: int) -> int | None:
        """Get the internal index for a given MIDI channel number."""
        for i, ch in enumerate(self.channels):
            if ch.channel == channel_number:
                return i
        return None

    def _calculate_assignment_score(
        self,
        freq_hz: float,
        amp_db: float,
        channel_idx: int,
        fundamental_hz: float | None = None,
        harmonic_number: int = 0,
        is_harmonic: bool = False,
    ) -> float:
        """
        Calculate assignment score for a peak to a channel.

        Considers frequency band membership, harmonic relationship to fundamental,
        and amplitude priority with formant-aware weighting.

        Args:
            freq_hz: Frequency of the peak
            amp_db: Amplitude of the peak in dB
            channel_idx: Index of the channel being scored
            fundamental_hz: Current detected vocal fundamental (optional)
            harmonic_number: Harmonic number of this peak (0 = not a harmonic)
            is_harmonic: Whether this peak aligns with the harmonic series

        Returns:
            Score value (higher is better)
        """
        min_freq, max_freq = self.get_frequency_range_for_channel(channel_idx)

        if not (min_freq <= freq_hz <= max_freq):
            return -float("inf")

        center_freq = (min_freq + max_freq) / 2
        score = amp_db

        edge_penalty_factor = 3.0
        freq_distance = abs(freq_hz - center_freq)
        max_distance = (max_freq - min_freq) / 2
        if max_distance > 0:
            edge_penalty = (freq_distance / max_distance) * edge_penalty_factor
            score -= edge_penalty

        if is_harmonic and fundamental_hz is not None:
            harmonic_bonus = 0.0

            if channel_idx < 3:
                if harmonic_number == 1:
                    harmonic_bonus = 20.0
                elif harmonic_number <= 3:
                    harmonic_bonus = 10.0

            elif channel_idx < 7:
                if harmonic_number >= 2 and harmonic_number <= 4:
                    harmonic_bonus = 15.0
                elif harmonic_number == 1:
                    harmonic_bonus = 8.0

            elif channel_idx < 11:
                if harmonic_number >= 3 and harmonic_number <= 6:
                    harmonic_bonus = 15.0
                elif harmonic_number >= 2 and harmonic_number <= 8:
                    harmonic_bonus = 5.0

            elif channel_idx < 14:
                if harmonic_number >= 4 and harmonic_number <= 8:
                    harmonic_bonus = 12.0

            elif channel_idx >= 14:
                if harmonic_number >= 8 and harmonic_number <= 20:
                    harmonic_bonus = 15.0
                elif harmonic_number >= 6 and harmonic_number <= 25:
                    harmonic_bonus = 8.0

            score += harmonic_bonus

        if channel_idx < 3 and fundamental_hz is not None:
            freq_distance_from_fund = abs(freq_hz - fundamental_hz)
            if freq_distance_from_fund < 20.0:
                score += 15.0

        return score

    def assign_bands_to_channels(
        self,
        frame_data: dict,
        frame_time: float,
    ) -> dict[int, tuple[float, float, int] | None]:
        """
        Assign frequency peaks to channels using formant-aware assignment.

        Uses a multi-pass approach:
        1. First pass assigns fundamental tracking channels (1-3)
        2. Second pass assigns harmonic peaks to appropriate formant channels
        3. Third pass handles remaining non-harmonic peaks

        Args:
            frame_data: Frame analysis data with 'peaks', 'fundamental_hz',
                       and 'harmonic_groups' keys
            frame_time: Current time in seconds

        Returns:
            Dict mapping channel number to assigned peak or None
        """
        assignments: dict[int, tuple[float, float, int] | None] = {}

        for ch in self.channels:
            assignments[ch.channel] = None

        peaks = frame_data.get("peaks", [])
        fundamental_hz = frame_data.get("fundamental_hz")
        harmonic_groups = frame_data.get("harmonic_groups", [])

        assigned_peaks: set[int] = set()
        used_channels: set[int] = set()

        sorted_harmonic_groups = sorted(
            harmonic_groups,
            key=lambda x: x["amplitude_db"],
            reverse=True,
        )

        for harmonic_info in sorted_harmonic_groups:
            if not harmonic_info["is_harmonic"]:
                continue

            freq_hz = harmonic_info["frequency_hz"]
            amp_db = harmonic_info["amplitude_db"]
            midi_note = harmonic_info["midi_note"]
            harmonic_number = harmonic_info["harmonic_number"]

            best_channel_idx: int | None = None
            best_score: float = -float("inf")

            for ch_idx, channel in enumerate(self.channels):
                if ch_idx in used_channels:
                    continue

                score = self._calculate_assignment_score(
                    freq_hz=freq_hz,
                    amp_db=amp_db,
                    channel_idx=ch_idx,
                    fundamental_hz=fundamental_hz,
                    harmonic_number=harmonic_number,
                    is_harmonic=True,
                )

                if score > best_score:
                    best_score = score
                    best_channel_idx = ch_idx

            if best_channel_idx is not None and best_score > -100.0:
                assignments[self.channels[best_channel_idx].channel] = (
                    freq_hz, amp_db, midi_note
                )
                assigned_peaks.add(peaks.index((freq_hz, amp_db, midi_note)))
                used_channels.add(best_channel_idx)

        for peak_idx, (freq_hz, amp_db, midi_note) in enumerate(peaks):
            if peak_idx in assigned_peaks:
                continue

            best_channel_idx: int | None = None
            best_score: float = -float("inf")

            for ch_idx, channel in enumerate(self.channels):
                if ch_idx in used_channels:
                    continue

                harmonic_number = 0
                is_harmonic = False

                for hg in harmonic_groups:
                    if (hg["frequency_hz"] == freq_hz and 
                        hg["amplitude_db"] == amp_db):
                        harmonic_number = hg["harmonic_number"]
                        is_harmonic = hg["is_harmonic"]
                        break

                score = self._calculate_assignment_score(
                    freq_hz=freq_hz,
                    amp_db=amp_db,
                    channel_idx=ch_idx,
                    fundamental_hz=fundamental_hz,
                    harmonic_number=harmonic_number,
                    is_harmonic=is_harmonic,
                )

                if score > best_score:
                    best_score = score
                    best_channel_idx = ch_idx

            if best_channel_idx is not None and best_score > -80.0:
                assignments[self.channels[best_channel_idx].channel] = (
                    freq_hz, amp_db, midi_note
                )
                used_channels.add(best_channel_idx)

        return assignments

    def update_channel_states(
        self, assignments: dict[int, tuple[float, float, int] | None], frame_time: float
    ):
        """Update internal channel states based on current assignments with formant stability."""
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
                    note_on_threshold = -40.0
                    if amp_db > note_on_threshold:
                        channel.active_note = midi_note
                        channel.note_start_time = frame_time
                        channel.target_frequency_hz = freq_hz
                        channel.note_stable_frames = 1
                        channel.formant_stability_count = 0
                else:
                    if midi_note != channel.active_note:
                        volume_diff = amp_db - channel.last_volume_db
                        
                        if volume_diff >= 9.0:
                            channel.active_note = midi_note
                            channel.target_frequency_hz = freq_hz
                            channel.note_start_time = frame_time
                            channel.note_stable_frames = 1
                            channel.formant_stability_count = 0
                        else:
                            if channel.target_frequency_hz is not None:
                                current_distance = abs(freq_hz - channel.target_frequency_hz)
                                prev_freq = channel.last_frequency_hz or freq_hz
                                prev_distance = abs(prev_freq - channel.target_frequency_hz)
                                
                                if current_distance < prev_distance * 0.8:
                                    channel.active_note = midi_note
                                    channel.target_frequency_hz = freq_hz
                            else:
                                channel.active_note = midi_note
                                channel.target_frequency_hz = freq_hz
                    else:
                        channel.note_stable_frames += 1
                        
                        if channel.target_frequency_hz is not None:
                            alpha = 0.3
                            channel.target_frequency_hz = (
                                alpha * freq_hz + (1 - alpha) * channel.target_frequency_hz
                            )

                    if channel.active_note is not None and channel.target_frequency_hz is not None:
                        expected_center = midi_to_hz(channel.active_note)
                        semitone_drift = abs(12.0 * np.log2(freq_hz / expected_center))
                        
                        if semitone_drift < 0.2:
                            channel.formant_stability_count += 1
                        else:
                            channel.formant_stability_count = max(0, channel.formant_stability_count - 1)

                        if (channel.formant_stability_count >= self.stability_threshold and
                            not channel.is_formant_stable):
                            channel.is_formant_stable = True

            else:
                if channel.active_note is not None:
                    last_vol = channel.last_volume_db
                    
                    if last_vol < -49.0 or last_vol < -35:
                        channel.active_note = None
                        channel.target_frequency_hz = None
                        channel.is_formant_stable = False
                        channel.formant_stability_count = 0
                
                channel.note_stable_frames = 0

    def get_active_notes(self) -> dict[int, int]:
        """Get currently active notes per channel."""
        return {
            ch.channel: ch.active_note
            for ch in self.channels
            if ch.active_note is not None
        }

    def get_formant_stability(self) -> dict[int, bool]:
        """Get formant stability status per channel."""
        return {
            ch.channel: ch.is_formant_stable
            for ch in self.channels
        }

    def reset_frame_count(self):
        """Reset frame counter for warm-up."""
        self.frame_count = 0
