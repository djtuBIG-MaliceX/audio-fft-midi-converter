"""Slot-based peak tracking channel mapper for speech-to-MIDI conversion.

Each channel maintains a persistent "slot" - a frequency trajectory it commits
to tracking. During warmup, channels pick peaks from strongest to weakest.
Once committed, a channel ONLY responds to peaks within 1 semitone of its slot.
If no peak is close enough, the channel goes silent (no assignment).

This prevents note flipping because channels don't chase different peaks -
they track their slot's frequency trajectory, and pitch bend handles all
frequency transitions within ±12 semitones.
"""

import numpy as np
from dataclasses import dataclass, field

from fft_analyzer import hz_to_midi, midi_to_hz


@dataclass
class ChannelState:
    """Track state for a single MIDI channel with slot-based tracking."""

    channel: int
    active_note: int | None = None
    tracked_frequency_hz: float | None = None
    target_frequency_hz: float | None = None
    last_frequency_hz: float | None = None
    last_volume_db: float = -float("inf")
    note_start_time: float = 0.0
    note_stable_frames: int = 0
    commitment_frames: int = 0
    is_committed: bool = False
    is_warmup: bool = True
    peak_absent_frames: int = 0
    formant_stability_count: int = 0
    is_formant_stable: bool = False
    fundamental_reference_hz: float | None = None
    slot_frequency_hz: float | None = None
    slot_midi_note: int = 0
    slot_active: bool = False


class ChannelMapper:
    """
    Slot-based peak tracking channel mapper for speech-to-MIDI conversion.

    Each channel maintains a persistent slot. During warmup (first 3 frames),
    channels pick peaks from strongest to weakest. Once committed, a channel
    ONLY responds to peaks within 1 semitone of its slot. If no peak is close
    enough, the channel goes silent.

    This prevents note flipping because channels don't chase different peaks -
    they track their slot's frequency trajectory, and pitch bend handles all
    frequency transitions within ±12 semitones.
    """

    # Configuration constants
    COMMIT_THRESHOLD = 3  # Frames before a channel becomes committed
    RELEASE_THRESHOLD_DB = -50.0  # Amplitude below which to release a peak
    RELEASE_ABSENT_FRAMES = 10  # Frames without peak before releasing
    SLOT_TOLERANCE_SEMITONES = 1.0  # Max semitone distance for slot matching
    TRACKING_ALPHA = 0.2  # Smoothing factor for frequency tracking
    SLOT_DRIFT_LIMIT_SEMITONES = 3.0  # Max drift from initial slot frequency

    def __init__(
        self,
        n_channels: int = 15,
        exclude_channel: int = 10,
        stability_threshold: int = 5,
        band_definitions: list[tuple[float, float]] | None = None,
    ):
        """
        Initialize channel mapper with slot-based tracking.

        Args:
            n_channels: Number of frequency-tracking channels (default 15)
            exclude_channel: Channel to exclude from frequency tracking
                (10 = percussion)
            stability_threshold: Frames needed before formant stable mode
            band_definitions: Unused, kept for API compatibility
        """
        self.n_channels = n_channels
        self.exclude_channel = exclude_channel
        self.stability_threshold = stability_threshold

        self.channels: list[ChannelState] = []
        channel_idx = 0

        for i in range(n_channels):
            midi_channel = i + 1 if i < exclude_channel - 1 else i + 2

            self.channels.append(
                ChannelState(
                    channel=midi_channel,
                )
            )

            channel_idx += 1

        self.frame_count = 0

    def _get_channel_index(self, channel_number: int) -> int | None:
        """Get the internal index for a given MIDI channel number."""
        for i, ch in enumerate(self.channels):
            if ch.channel == channel_number:
                return i
        return None

    def _semitone_distance(self, freq1: float, freq2: float) -> float:
        """Calculate semitone distance between two frequencies."""
        if freq1 <= 0 or freq2 <= 0:
            return float("inf")
        return 12.0 * np.log2(freq2 / freq1)

    def assign_bands_to_channels(
        self,
        frame_data: dict,
        frame_time: float,
    ) -> dict[int, tuple[float, float, int] | None]:
        """
        Assign frequency peaks to channels using slot-based tracking.

        During warmup, channels pick peaks from strongest to weakest.
        After warmup, committed channels only respond to peaks within
        1 semitone of their slot. If no peak is close enough, the
        channel goes silent (no assignment).

        Args:
            frame_data: Frame analysis data with 'peaks', 'fundamental_hz',
                        and 'harmonic_groups' keys
            frame_time: Current time in seconds

        Returns:
            Dict mapping channel number to (freq_hz, amp_db, midi_note) or None
        """
        assignments: dict[int, tuple[float, float, int] | None] = {}
        for ch in self.channels:
            assignments[ch.channel] = None

        peaks = frame_data.get("peaks", [])

        # Sort peaks by amplitude (strongest first) for assignment
        sorted_peak_indices = sorted(
            range(len(peaks)),
            key=lambda i: peaks[i][1],  # amp_db
            reverse=True,
        )

        assigned_peaks: set[int] = set()
        used_channels: set[int] = set()

        # Phase 1: Committed channels claim their slot (peak within tolerance)
        for ch_idx, channel in enumerate(self.channels):
            if not channel.is_committed:
                continue

            if not channel.slot_active or channel.slot_frequency_hz is None:
                continue

            # Find closest peak to this channel's slot frequency
            best_peak_idx: int | None = None
            best_distance: float = float("inf")

            for peak_idx in range(len(peaks)):
                if peak_idx in assigned_peaks:
                    continue

                freq_hz = peaks[peak_idx][0]
                dist = abs(
                    self._semitone_distance(channel.slot_frequency_hz, freq_hz)
                )

                if dist < best_distance:
                    best_distance = dist
                    best_peak_idx = peak_idx

            # Only accept if within slot tolerance
            if best_peak_idx is not None and best_distance <= self.SLOT_TOLERANCE_SEMITONES:
                freq_hz, amp_db, midi_note = peaks[best_peak_idx]
                assignments[channel.channel] = (freq_hz, amp_db, midi_note)
                assigned_peaks.add(best_peak_idx)
                used_channels.add(ch_idx)
            else:
                # No peak close enough - channel goes silent
                # This is intentional: the slot maintains its trajectory
                pass

        # Phase 2: Free channels pick strongest available peaks
        peak_idx_counter = 0
        for ch_idx, channel in enumerate(self.channels):
            if ch_idx in used_channels:
                continue

            while peak_idx_counter < len(sorted_peak_indices):
                candidate_peak_idx = sorted_peak_indices[peak_idx_counter]
                peak_idx_counter += 1

                if candidate_peak_idx not in assigned_peaks:
                    freq_hz, amp_db, midi_note = peaks[candidate_peak_idx]
                    assignments[channel.channel] = (freq_hz, amp_db, midi_note)
                    assigned_peaks.add(candidate_peak_idx)
                    used_channels.add(ch_idx)
                    break

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
                channel.peak_absent_frames = 0

                if self.frame_count <= warmup_frames:
                    channel.is_warmup = True
                    channel.target_frequency_hz = freq_hz
                    channel.tracked_frequency_hz = freq_hz
                    channel.slot_frequency_hz = freq_hz
                    channel.slot_midi_note = midi_note
                    channel.slot_active = True
                    continue

                channel.is_warmup = False

                # Update tracked frequency with smoothing
                if channel.tracked_frequency_hz is None:
                    channel.tracked_frequency_hz = freq_hz

                alpha = self.TRACKING_ALPHA
                channel.tracked_frequency_hz = (
                    alpha * freq_hz + (1 - alpha) * channel.tracked_frequency_hz
                )

                # Update target frequency
                if channel.target_frequency_hz is None:
                    channel.target_frequency_hz = freq_hz
                else:
                    channel.target_frequency_hz = (
                        alpha * freq_hz + (1 - alpha) * channel.target_frequency_hz
                    )

                # Update slot frequency - this is the PERSISTENT trajectory
                if channel.slot_frequency_hz is None:
                    channel.slot_frequency_hz = freq_hz
                else:
                    slot_alpha = 0.15  # Very slow slot updates
                    channel.slot_frequency_hz = (
                        slot_alpha * freq_hz
                        + (1 - slot_alpha) * channel.slot_frequency_hz
                    )

                channel.slot_active = True

                # Handle note changes
                if channel.active_note is None:
                    if amp_db > -40.0:
                        channel.active_note = midi_note
                        channel.note_start_time = frame_time
                        channel.note_stable_frames = 1
                        channel.formant_stability_count = 0
                        channel.slot_midi_note = midi_note
                else:
                    channel.note_stable_frames += 1

                    # Formant stability tracking
                    if channel.active_note is not None:
                        expected_center = midi_to_hz(channel.active_note)
                        semitone_drift = abs(
                            self._semitone_distance(expected_center, freq_hz)
                        )

                        if semitone_drift < 0.2:
                            channel.formant_stability_count += 1
                        else:
                            channel.formant_stability_count = max(
                                0, channel.formant_stability_count - 1
                            )

                        if (
                            channel.formant_stability_count
                            >= self.stability_threshold
                            and not channel.is_formant_stable
                        ):
                            channel.is_formant_stable = True

                # Commitment logic
                if not channel.is_committed:
                    channel.commitment_frames += 1
                    if channel.commitment_frames >= self.COMMIT_THRESHOLD:
                        channel.is_committed = True
            else:
                # No peak assigned this frame
                channel.peak_absent_frames += 1

                if channel.is_committed and channel.slot_active:
                    last_vol = channel.last_volume_db

                    if (
                        last_vol < self.RELEASE_THRESHOLD_DB
                        or channel.peak_absent_frames
                        >= self.RELEASE_ABSENT_FRAMES
                    ):
                        channel.slot_active = False
                        channel.slot_frequency_hz = None

                if channel.active_note is not None:
                    last_vol = channel.last_volume_db
                    if last_vol < -45.0 or channel.peak_absent_frames > 15:
                        channel.active_note = None
                        channel.target_frequency_hz = None
                        channel.is_formant_stable = False
                        channel.formant_stability_count = 0
                        channel.tracked_frequency_hz = None
                        channel.slot_active = False
                        channel.slot_frequency_hz = None

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
