"""MIDI event generation logic for audio-to-MIDI conversion with formant awareness."""

import numpy as np
from dataclasses import dataclass, field


@dataclass
class MidiEvent:
    """Represents a single MIDI event."""

    time: float  # Time in seconds
    event_type: str  # 'note_on', 'note_off', 'pitch_bend', 'cc'
    channel: int
    data: dict = field(default_factory=dict)


class MidiEventGenerator:
    """
    Generate MIDI events from frequency analysis using talking piano approach.

    Key improvements over previous version:
    - Minimal pitch bend (only for large frequency jumps within sustained phonemes)
    - Aggressive note quantization to reduce chatter
    - Velocity mapped from amplitude for expressiveness
    - Higher thresholds for triggering new notes (reduces note flipping)
    - Hysteresis in note on/off decisions
    """

    def __init__(
        self,
        bpm: int = 120,
        ticks_per_beat: int = 480,
        pitch_bend_range: int = 12,
        velocity: int = 100,
        volume_cc: int = 7,
        min_pitch_bend_semitones: float = 1.5,
    ):
        """
        Initialize MIDI event generator.

        Args:
            bpm: Beats per minute (default 120)
            ticks_per_beat: MIDI ticks per quarter note (default 480)
            pitch_bend_range: Pitch bend range in semitones (default 12)
            velocity: Fixed note velocity 1-127 (default 100)
            volume_cc: CC number for channel volume (default 7)
            min_pitch_bend_semitones: Minimum semitone drift to trigger pitch bend
        """
        self.bpm = bpm
        self.ticks_per_beat = ticks_per_beat
        self.pitch_bend_range = pitch_bend_range
        self.velocity = velocity
        self.volume_cc = volume_cc
        self.min_pitch_bend_semitones = min_pitch_bend_semitones

        # State tracking per channel
        self.channel_state: dict[int, dict] = {}

        # Events list
        self.events: list[MidiEvent] = []

    def _calculate_pitch_bend_value(self, semitone_offset: float) -> tuple[int, int]:
        """
        Calculate 14-bit pitch bend value for given semitone offset.

        MIDI pitch bend is a 14-bit value (0-16383), with center at 8192.
        """
        semitone_offset = max(
            -self.pitch_bend_range, min(self.pitch_bend_range, semitone_offset)
        )

        bend_value = int(8192 + (semitone_offset / self.pitch_bend_range) * 8191)
        bend_value = max(0, min(16383, bend_value))

        lsb = bend_value & 0x7F
        msb = (bend_value >> 7) & 0x7F

        return lsb, msb

    def _semitones_between_frequencies(self, freq1: float, freq2: float) -> float:
        """Calculate true semitone distance between two frequencies."""
        if freq1 <= 0 or freq2 <= 0:
            return 0.0
        return 12 * np.log2(freq2 / freq1)

    def _semitone_distance(self, note1: int, note2: int) -> float:
        """Calculate semitone distance between MIDI notes."""
        return float(note2 - note1)

    def should_trigger_new_note(
        self,
        current_midi_note: int,
        last_note: int | None,
        current_freq_hz: float,
        last_frequency_hz: float | None,
        current_volume_db: float,
        last_volume_db: float,
    ) -> bool:
        """
        Determine if a new note-on event should be triggered.

        Prefers pitch bend over note changes for speech - only trigger a new
        note when the frequency drift is large enough that pitch bend alone
        cannot handle it (beyond ±12 semitones).

        However, if the MIDI note number has changed by 6+ semitones (half
        octave), trigger a new note even if the frequency drift is smaller.
        This handles cases where the center of energy in a band has shifted
        significantly.
        """
        if last_note is None:
            return True

        note_distance = abs(self._semitone_distance(current_midi_note, last_note or 0))

        # Large note distance (octave jump or more) always triggers a new note
        if note_distance > self.pitch_bend_range:
            return True

        # Also trigger if note distance > 6 semitones (half octave)
        # This catches center-of-energy shifts that the frequency drift
        # check might miss
        if note_distance >= 6:
            return True

        # Check actual frequency drift
        if last_frequency_hz is not None and current_freq_hz > 0:
            semitone_drift = abs(
                self._semitones_between_frequencies(last_frequency_hz, current_freq_hz)
            )

            # If frequency drift is within pitch bend range, use pitch bend
            # instead of triggering a new note.
            if semitone_drift <= self.pitch_bend_range:
                return False

            # Only trigger new note if drift exceeds pitch bend range
            if semitone_drift > self.pitch_bend_range + 1.0:
                return True

        return False

    def _calculate_velocity_from_db(self, amp_db: float) -> int:
        """
        Calculate MIDI velocity from amplitude in dB.

        Maps -60dB to 0, 0dB to 127 for expressive dynamics.
        """
        velocity = int(((amp_db + 60) / 60) * 127)
        return max(1, min(127, velocity))

    def process_frame(
        self,
        assignments: dict[int, tuple[float, float, int] | None],
        frame_time: float,
    ):
        """
        Process a single analysis frame and generate MIDI events.

        Talking piano approach: prioritize clean note on/off with minimal pitch bend.
        Pitch bend only used for major frequency corrections, not fine tracking.
        """
        for channel, peak in assignments.items():
            if channel not in self.channel_state:
                self.channel_state[channel] = {
                    "active_note": None,
                    "last_frequency_hz": None,
                    "last_midi_note": None,
                    "last_volume_db": -float("inf"),
                }

            state = self.channel_state[channel]

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

            last_freq_hz = state.get("last_frequency_hz")
            last_note = state.get("last_midi_note")

            should_new_note = self.should_trigger_new_note(
                midi_note,
                last_note,
                freq_hz,
                last_freq_hz,
                amp_db,
                state["last_volume_db"],
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

                velocity = self._calculate_velocity_from_db(amp_db)
                self.events.append(
                    MidiEvent(
                        time=frame_time,
                        event_type="note_on",
                        channel=channel,
                        data={"note": midi_note, "velocity": velocity},
                    )
                )

                state["active_note"] = midi_note

            if state["active_note"] is not None:
                expected_center = 440.0 * (2.0 ** ((state["active_note"] - 69) / 12.0))
                semitone_drift = self._semitones_between_frequencies(
                    expected_center, freq_hz
                )

                if abs(semitone_drift) > self.min_pitch_bend_semitones:
                    lsb, msb = self._calculate_pitch_bend_value(semitone_drift)

                    last_bend = state.get("last_pitch_bend")
                    if last_bend is None or frame_time - state.get(
                        "last_pitch_bend_time", 0
                    ) > 0.1:
                        current_bend = (lsb, msb)
                        if last_bend is None or abs(current_bend[0] - last_bend[0]) > 2:
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
                or abs(normalized_volume - state["last_volume_cc"]) > 3
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
        """Send note-off events for all active notes at the end."""
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
