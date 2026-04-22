"""MIDI event generation logic for audio-to-MIDI conversion with formant awareness."""

import numpy as np
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class MidiEvent:
    """Represents a single MIDI event."""

    time: float  # Time in seconds
    event_type: str  # 'note_on', 'note_off', 'pitch_bend', 'cc'
    channel: int
    data: dict = field(default_factory=dict)


class MidiEventGenerator:
    """
    Generate MIDI events from frequency analysis with formant-aware pitch bend.

    Implements:
    - Reduced EMA smoothing (alpha=0.15) for smoother but more responsive tracking
    - Dynamic pitch bend threshold based on formant stability
    - Formant stability propagation from channel mapper
    - Cleaner transitions with higher thresholds for stable formants
    """

    def __init__(
        self,
        bpm: int = 120,
        ticks_per_beat: int = 480,
        pitch_bend_range: int = 12,
        velocity: int = 100,
        volume_cc: int = 7,
    ):
        """
        Initialize MIDI event generator.

        Args:
            bpm: Beats per minute (default 120)
            ticks_per_beat: MIDI ticks per quarter note (default 480)
            pitch_bend_range: Pitch bend range in semitones (default 12)
            velocity: Fixed note velocity 1-127 (default 100)
            volume_cc: CC number for channel volume (default 7)
        """
        self.bpm = bpm
        self.ticks_per_beat = ticks_per_beat
        self.pitch_bend_range = pitch_bend_range
        self.velocity = velocity
        self.volume_cc = volume_cc

        # State tracking per channel
        self.channel_state: dict[int, dict] = {}

        # Events list
        self.events: list[MidiEvent] = []

    def _calculate_pitch_bend_value(self, semitone_offset: float) -> tuple[int, int]:
        """
        Calculate 14-bit pitch bend value for given semitone offset.

        MIDI pitch bend is a 14-bit value (0-16383), with center at 8192.

        Args:
            semitone_offset: Offset from center pitch in semitones (-range to +range)

        Returns:
            Tuple of (LSB, MSB) for MIDI pitch bend message
        """
        semitone_offset = max(
            -self.pitch_bend_range, min(self.pitch_bend_range, semitone_offset)
        )

        bend_value = int(8192 + (semitone_offset / self.pitch_bend_range) * 8191)
        bend_value = max(0, min(16383, bend_value))

        lsb = bend_value & 0x7F
        msb = (bend_value >> 7) & 0x7F

        return lsb, msb

    def _semitones_between_notes(self, note1: int, note2: int) -> float:
        """Calculate semitone distance between two MIDI notes."""
        return float(note2 - note1)

    def _semitones_between_frequencies(self, freq1: float, freq2: float) -> float:
        """Calculate true semitone distance between two frequencies."""
        if freq1 <= 0 or freq2 <= 0:
            return 0.0
        return 12 * np.log2(freq2 / freq1)

    def should_trigger_new_note(
        self,
        current_midi_note: int,
        last_note: int | None,
        current_freq_hz: float,
        last_frequency_hz: float | None,
        current_volume_db: float,
        last_volume_db: float,
        is_formant_stable: bool = False,
    ) -> bool:
        """
        Determine if a new note-on event should be triggered.

        In stable formant mode, requires larger frequency jumps to trigger new notes,
        preferring pitch bend adjustments instead. This reduces note chatter on
        sustained vowels and produces cleaner sound.

        Args:
            current_midi_note: Current MIDI note number
            last_note: Previously active note number (None if no previous note)
            current_freq_hz: Current frequency in Hz
            last_frequency_hz: Last tracked frequency (None if not tracking)
            current_volume_db: Current amplitude in dB
            last_volume_db: Previous amplitude in dB
            is_formant_stable: Whether this channel has entered stable formant mode

        Returns:
            True if new note-on should be triggered
        """
        if last_note is None:
            return True

        volume_jump = current_volume_db - last_volume_db
        if volume_jump >= 9.0:
            return True

        if last_frequency_hz is not None and current_freq_hz > 0:
            semitone_drift = self._semitones_between_frequencies(
                last_frequency_hz, current_freq_hz
            )

            if is_formant_stable:
                if abs(semitone_drift) < 1.5:
                    return False

            if abs(semitone_drift) > self.pitch_bend_range:
                return True

        return False

    def initialize_pitch_bend_range(self, channel: int, time: float):
        """
        Set extended pitch bend range for a channel using CC100/CC101/CC6.

        CC100 (RPN LSB) = 0
        CC101 (RPN MSB) = 0  (selects Pitch Bend Range)
        CC6 (Data Entry LSB) = 24 (set range to 24 semitones)
        CC38 (Data Entry MSB) = 0

        Args:
            channel: MIDI channel (1-16)
            time: Time in seconds
        """
        self.events.append(
            MidiEvent(
                time=time,
                event_type="cc",
                channel=channel,
                data={"cc_number": 101, "value": 0},
            )
        )
        self.events.append(
            MidiEvent(
                time=time,
                event_type="cc",
                channel=channel,
                data={"cc_number": 100, "value": 0},
            )
        )

        self.events.append(
            MidiEvent(
                time=time,
                event_type="cc",
                channel=channel,
                data={"cc_number": 38, "value": 0},
            )
        )
        self.events.append(
            MidiEvent(
                time=time,
                event_type="cc",
                channel=channel,
                data={
                    "cc_number": 6,
                    "value": self.pitch_bend_range,
                },
            )
        )

        self.events.append(
            MidiEvent(
                time=time,
                event_type="cc",
                channel=channel,
                data={"cc_number": 101, "value": 127},
            )
        )
        self.events.append(
            MidiEvent(
                time=time,
                event_type="cc",
                channel=channel,
                data={"cc_number": 100, "value": 127},
            )
        )

    def process_frame(
        self,
        assignments: dict[int, tuple[float, float, int] | None],
        frame_time: float,
        formant_stability: dict[int, bool] | None = None,
    ):
        """
        Process a single analysis frame and generate MIDI events.

        Uses formant stability information to dynamically adjust pitch bend
        sensitivity. Stable formants get higher thresholds, reducing warbling
        on sustained vowels while maintaining responsiveness during transitions.

        Args:
            assignments: Dict mapping channel to (freq_hz, amp_db, midi_note) or None
            frame_time: Current time in seconds
            formant_stability: Dict mapping channel to stability status (optional)
        """
        if formant_stability is None:
            formant_stability = {}

        for channel, peak in assignments.items():
            if channel not in self.channel_state:
                self.channel_state[channel] = {
                    "active_note": None,
                    "last_frequency_hz": None,
                    "last_midi_note": None,
                    "last_volume_db": -float("inf"),
                    "pitch_bend_initialized": False,
                    "smoothed_frequency_hz": None,
                    "is_formant_stable": False,
                }

            state = self.channel_state[channel]
            is_formant_stable = formant_stability.get(channel, False)

            if peak is None:
                if state["active_note"] is not None:
                    self.events.append(
                        MidiEvent(
                            time=frame_time,
                            event_type="note_off",
                            channel=channel,
                            data={"note": state["active_note"], "velocity": 0},
                        )
                    )
                    state["active_note"] = None
                continue

            freq_hz, amp_db, midi_note = peak

            if not state["pitch_bend_initialized"]:
                self.initialize_pitch_bend_range(channel, frame_time)
                state["pitch_bend_initialized"] = True

            last_freq_hz = state.get("last_frequency_hz")
            last_note = state.get("last_midi_note")

            should_new_note = self.should_trigger_new_note(
                midi_note, last_note, freq_hz, last_freq_hz, amp_db,
                state["last_volume_db"], is_formant_stable
            )

            if should_new_note:
                if state["active_note"] is not None:
                    self.events.append(
                        MidiEvent(
                            time=frame_time,
                            event_type="note_off",
                            channel=channel,
                            data={"note": state["active_note"], "velocity": 0},
                        )
                    )

                self.events.append(
                    MidiEvent(
                        time=frame_time,
                        event_type="note_on",
                        channel=channel,
                        data={"note": midi_note, "velocity": self.velocity},
                    )
                )

                state["active_note"] = midi_note
                state["smoothed_frequency_hz"] = freq_hz

            if state["active_note"] is not None:
                expected_center = 440.0 * (2.0 ** ((state["active_note"] - 69) / 12.0))
                semitone_drift = self._semitones_between_frequencies(
                    expected_center, freq_hz
                )
            else:
                semitone_drift = 0.0

            if state["smoothed_frequency_hz"] is None:
                state["smoothed_frequency_hz"] = freq_hz
            else:
                alpha = 0.15
                state["smoothed_frequency_hz"] = (
                    alpha * freq_hz + (1 - alpha) * state["smoothed_frequency_hz"]
                )

            if state["active_note"] is not None:
                expected_center = 440.0 * (2.0 ** ((state["active_note"] - 69) / 12.0))
                smoothed_semitone_drift = self._semitones_between_frequencies(
                    expected_center, state["smoothed_frequency_hz"]
                )
            else:
                smoothed_semitone_drift = 0.0

            if is_formant_stable:
                pitch_bend_threshold = 0.5
            else:
                pitch_bend_threshold = 0.3

            send_pitch_bend = False

            if abs(smoothed_semitone_drift) > pitch_bend_threshold:
                lsb, msb = self._calculate_pitch_bend_value(smoothed_semitone_drift)

                current_bend = (lsb, msb)
                last_bend = state.get("last_pitch_bend")

                if last_bend is None:
                    send_pitch_bend = True
                else:
                    last_time = state.get("last_pitch_bend_time", 0)
                    time_since_last = frame_time - last_time
                    
                    if time_since_last >= 0.08:
                        bend_diff = abs(current_bend[0] - last_bend[0]) + abs(current_bend[1] - last_bend[1])
                        if bend_diff > 10:
                            send_pitch_bend = True

            if send_pitch_bend:
                lsb, msb = self._calculate_pitch_bend_value(smoothed_semitone_drift)
                current_bend = (lsb, msb)

                self.events.append(
                    MidiEvent(
                        time=frame_time,
                        event_type="pitch_bend",
                        channel=channel,
                        data={"lsb": lsb, "msb": msb},
                    )
                )
                state["last_pitch_bend"] = current_bend
                state["last_pitch_bend_time"] = frame_time

            normalized_volume = int(((amp_db + 60) / 60) * 127)
            normalized_volume = max(0, min(127, normalized_volume))

            if (
                "last_volume_cc" not in state
                or abs(normalized_volume - state["last_volume_cc"]) > 1
            ):
                self.events.append(
                    MidiEvent(
                        time=frame_time,
                        event_type="cc",
                        channel=channel,
                        data={"cc_number": self.volume_cc, "value": normalized_volume},
                    )
                )
                state["last_volume_cc"] = normalized_volume

            state["last_midi_note"] = midi_note
            state["last_frequency_hz"] = freq_hz
            state["last_volume_db"] = amp_db

    def finalize(self, end_time: float):
        """
        Send note-off events for all active notes at the end.

        Args:
            end_time: End time in seconds
        """
        for channel, state in self.channel_state.items():
            if state["active_note"] is not None:
                self.events.append(
                    MidiEvent(
                        time=end_time,
                        event_type="note_off",
                        channel=channel,
                        data={"note": state["active_note"], "velocity": 0},
                    )
                )
