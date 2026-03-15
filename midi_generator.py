"""MIDI event generation logic for audio-to-MIDI conversion."""

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
    Generate MIDI events from frequency analysis with pitch bend support.

    Implements extended pitch bend range (±24 semitones) via CC100/CC101/CC6.
    Tracks continuous frequencies and only triggers new notes when necessary.
    """

    def __init__(
        self,
        bpm: int = 120,
        ticks_per_beat: int = 480,
        pitch_bend_range: int = 24,
        velocity: int = 100,
        volume_cc: int = 7,
        expression_cc: int = 11,
    ):
        """
        Initialize MIDI event generator.

        Args:
            bpm: Beats per minute (default 120)
            ticks_per_beat: MIDI ticks per quarter note (default 480)
            pitch_bend_range: Pitch bend range in semitones (default 24)
            velocity: Fixed note velocity 1-127 (default 100)
            volume_cc: CC number for channel volume (default 7)
            expression_cc: CC number for expression control (default 11)
        """
        self.bpm = bpm
        self.ticks_per_beat = ticks_per_beat
        self.pitch_bend_range = pitch_bend_range
        self.velocity = velocity
        self.volume_cc = volume_cc
        self.expression_cc = expression_cc

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
        # Clamp to ±pitch_bend_range semitones
        semitone_offset = max(
            -self.pitch_bend_range, min(self.pitch_bend_range, semitone_offset)
        )

        # Calculate 14-bit value: center=8192, range=±8191
        bend_value = int(8192 + (semitone_offset / self.pitch_bend_range) * 8191)
        bend_value = max(0, min(16383, bend_value))  # Ensure valid range

        # Split into LSB and MSB (7 bits each)
        lsb = bend_value & 0x7F
        msb = (bend_value >> 7) & 0x7F

        return lsb, msb

    def _semitones_between(self, note1: int, note2: int) -> float:
        """Calculate semitone distance between two MIDI notes."""
        return float(note2 - note1)

    def should_trigger_new_note(
        self,
        current_note: int,
        last_note: int | None,
        current_volume_db: float,
        last_volume_db: float,
    ) -> bool:
        """
        Determine if a new note-on event should be triggered.

        Triggers new note when:
        1. Frequency drift exceeds 7 semitones (a fifth) - always new note
        2. Sudden volume increase ≥6dB

        Args:
            current_note: Current MIDI note number
            last_note: Previously active note number (None if no previous note)
            current_volume_db: Current amplitude in dB
            last_volume_db: Previous amplitude in dB

        Returns:
            True if new note-on should be triggered
        """
        # No previous note = definitely need new note
        if last_note is None:
            return True

        # Check frequency drift beyond 7 semitones (a fifth) - always new note
        semitone_drift = abs(self._semitones_between(last_note, current_note))
        if semitone_drift > 7:
            return True

        # Check sudden volume increase (≥6dB threshold)
        volume_jump = current_volume_db - last_volume_db
        if volume_jump >= 6.0:
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
        # Select Pitch Bend Range parameter (RPN)
        self.events.append(
            MidiEvent(
                time=time,
                event_type="cc",
                channel=channel,
                data={"cc_number": 101, "value": 0},  # RPN MSB = 0 (Pitch Bend Range)
            )
        )
        self.events.append(
            MidiEvent(
                time=time,
                event_type="cc",
                channel=channel,
                data={"cc_number": 100, "value": 0},  # RPN LSB = 0
            )
        )

        # Set pitch bend range to 24 semitones
        self.events.append(
            MidiEvent(
                time=time,
                event_type="cc",
                channel=channel,
                data={"cc_number": 38, "value": 0},  # Data Entry MSB = 0
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
                },  # Data Entry LSB = 24
            )
        )

        # Deselect RPN (null parameter)
        self.events.append(
            MidiEvent(
                time=time,
                event_type="cc",
                channel=channel,
                data={"cc_number": 101, "value": 127},  # RPN MSB = 127 (null)
            )
        )
        self.events.append(
            MidiEvent(
                time=time,
                event_type="cc",
                channel=channel,
                data={"cc_number": 100, "value": 127},  # RPN LSB = 127 (null)
            )
        )

    def process_frame(
        self, assignments: dict[int, tuple[float, float, int] | None], frame_time: float
    ):
        """
        Process a single analysis frame and generate MIDI events.

        Args:
            assignments: Dict mapping channel to (freq_hz, amp_db, midi_note) or None
            frame_time: Current time in seconds
        """
        for channel, peak in assignments.items():
            # Initialize channel state if needed
            if channel not in self.channel_state:
                self.channel_state[channel] = {
                    "active_note": None,
                    "last_frequency_hz": None,
                    "last_midi_note": None,
                    "last_volume_db": -float("inf"),
                    "pitch_bend_initialized": False,
                }

            state = self.channel_state[channel]

            # Initialize pitch bend range on first use
            if not state["pitch_bend_initialized"]:
                self.initialize_pitch_bend_range(channel, frame_time)
                state["pitch_bend_initialized"] = True

            if peak is None:
                # No frequency assigned - turn off note if active
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

            # Check if we need a new note or just pitch bend
            should_new_note = self.should_trigger_new_note(
                midi_note, state["last_midi_note"], amp_db, state["last_volume_db"]
            )

            if should_new_note:
                # Turn off previous note if active
                if state["active_note"] is not None:
                    self.events.append(
                        MidiEvent(
                            time=frame_time,
                            event_type="note_off",
                            channel=channel,
                            data={"note": state["active_note"], "velocity": 0},
                        )
                    )

                # Play new note
                self.events.append(
                    MidiEvent(
                        time=frame_time,
                        event_type="note_on",
                        channel=channel,
                        data={"note": midi_note, "velocity": self.velocity},
                    )
                )

                state["active_note"] = midi_note
            else:
                # Same note - apply pitch bend if frequency drifted
                if (
                    state["last_midi_note"] is not None
                    and state["last_frequency_hz"] is not None
                ):
                    semitone_drift = self._semitones_between(
                        state["last_midi_note"], midi_note
                    )

                    # Only send pitch bend if there's actual drift
                    if abs(semitone_drift) > 0.1:  # Threshold to avoid noise
                        lsb, msb = self._calculate_pitch_bend_value(semitone_drift)
                        self.events.append(
                            MidiEvent(
                                time=frame_time,
                                event_type="pitch_bend",
                                channel=channel,
                                data={"lsb": lsb, "msb": msb},
                            )
                        )

            # Update volume/expression based on amplitude
            # Normalize dB to 0-127 range (assuming -60dB to 0dB is typical range)
            normalized_volume = int(((amp_db + 60) / 60) * 127)
            normalized_volume = max(0, min(127, normalized_volume))

            self.events.append(
                MidiEvent(
                    time=frame_time,
                    event_type="cc",
                    channel=channel,
                    data={"cc_number": self.volume_cc, "value": normalized_volume},
                )
            )

            # Also update expression for finer control
            self.events.append(
                MidiEvent(
                    time=frame_time,
                    event_type="cc",
                    channel=channel,
                    data={"cc_number": self.expression_cc, "value": normalized_volume},
                )
            )

            # Update state
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
