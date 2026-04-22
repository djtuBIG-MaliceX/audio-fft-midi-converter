"""MIDI file writer module using mido library."""

import mido
from mido import MidiFile, MidiTrack, Message
from pathlib import Path

from midi_generator import MidiEvent, MidiEventGenerator


class MidiFileWriter:
    """
    Write MIDI events to Standard MIDI File format.

    Creates Type 1 MIDI files with separate tracks per channel for cleaner organization.
    """

    def __init__(self, bpm: int = 120, ticks_per_beat: int = 480):
        """
        Initialize MIDI file writer.

        Args:
            bpm: Beats per minute (default 120)
            ticks_per_beat: Ticks per quarter note (default 480)
        """
        self.bpm = bpm
        self.ticks_per_beat = ticks_per_beat

        # Create MIDI file with Type 1 format (multiple tracks)
        self.mid = MidiFile(type=1, ticks_per_beat=ticks_per_beat)

        # Track mapping: channel -> MidiTrack
        self.tracks: dict[int, MidiTrack] = {}

    def _seconds_to_ticks(self, seconds: float) -> int:
        """Convert time in seconds to MIDI ticks."""
        # Calculate ticks per second
        ticks_per_second = (self.ticks_per_beat * self.bpm) / 60.0
        return int(seconds * ticks_per_second)

    def _get_track_for_channel(self, channel: int) -> MidiTrack:
        """Get or create track for a MIDI channel."""
        if channel not in self.tracks:
            track = MidiTrack()
            self.mid.tracks.append(track)
            self.tracks[channel] = track

        return self.tracks[channel]

    def _channel_to_mido_channel(self, channel: int) -> int:
        """Convert 1-16 channel to mido's 0-15 channel."""
        return max(0, min(15, channel - 1))

    def write_events(self, events: list[MidiEvent], total_duration: float):
        """
        Write MIDI events to file.

        Args:
            events: List of MidiEvent objects
            total_duration: Total duration in seconds
        """
        # Sort events by time
        sorted_events = sorted(events, key=lambda e: e.time)

        # Group events by channel and convert to delta times
        channel_events: dict[int, list[tuple[int, MidiEvent]]] = {}

        for event in sorted_events:
            ticks = self._seconds_to_ticks(event.time)
            ch = event.channel

            if ch not in channel_events:
                channel_events[ch] = []
            channel_events[ch].append((ticks, event))

        # Create separate track for tempo
        tempo_track = MidiTrack()
        self.mid.tracks.append(tempo_track)

        # Add tempo message to tempo track
        # Tempo: microseconds per quarter note
        us_per_beat = int(60_000_000 / self.bpm)
        tempo_track.append(mido.MetaMessage("set_tempo", tempo=us_per_beat, time=0))

        # Add track name to tempo track
        tempo_track.append(mido.MetaMessage("track_name", name="Tempo", time=0))

        # Write events to tracks with proper delta times
        for channel, ch_events in channel_events.items():
            track = self._get_track_for_channel(channel)
            mido_channel = self._channel_to_mido_channel(channel)

            # Add program change 79 (ocarina) to all tracks
            track.append(
                Message("program_change", channel=mido_channel, program=79, time=0)
            )

            # Add CC91 (damper pedal) set to 0 to all tracks
            track.append(
                Message(
                    "control_change", channel=mido_channel, control=91, value=0, time=0
                )
            )

            # Add track name
            track_name = f"Channel {channel}" if channel != 10 else "Percussion"
            track.append(mido.MetaMessage("track_name", name=track_name, time=0))

            # Write events with delta times
            last_ticks = 0
            for ticks, event in ch_events:
                delta = ticks - last_ticks

                if event.event_type == "note_on":
                    msg = Message(
                        "note_on",
                        channel=mido_channel,
                        note=event.data["note"],
                        velocity=event.data["velocity"],
                        time=delta,
                    )
                elif event.event_type == "note_off":
                    msg = Message(
                        "note_off",
                        channel=mido_channel,
                        note=event.data["note"],
                        velocity=event.data["velocity"],
                        time=delta,
                    )
                elif event.event_type == "pitch_bend":
                    # Convert 14-bit unsigned (0-16383) to signed (-8192 to 8191) for mido
                    bend_value = event.data["lsb"] | (event.data["msb"] << 7)
                    signed_pitch = bend_value - 8192  # Convert to signed range
                    msg = Message(
                        "pitchwheel",
                        channel=mido_channel,
                        pitch=signed_pitch,
                        time=delta,
                    )
                elif event.event_type == "cc":
                    msg = Message(
                        "control_change",
                        channel=mido_channel,
                        control=event.data["cc_number"],
                        value=event.data["value"],
                        time=delta,
                    )
                else:
                    # Skip unknown event types
                    last_ticks = ticks
                    continue

                track.append(msg)
                last_ticks = ticks

        # Ensure all tracks end properly
        for track in self.mid.tracks:
            # Add end of track marker if not present
            if len(track) == 0 or not str(track[-1]).startswith("end_of_track"):
                track.append(mido.MetaMessage("end_of_track", time=0))

    def save(self, filepath: str):
        """
        Save MIDI file to disk.

        Args:
            filepath: Output file path (should end with .mid)
        """
        path = Path(filepath)

        # Ensure .mid extension
        if path.suffix.lower() != ".mid":
            path = path.with_suffix(".mid")

        self.mid.save(str(path))
        print(f"MIDI file saved: {path}")


def generate_midi_from_audio(
    audio_path: str,
    output_path: str,
    bpm: int = 120,
    ticks_per_beat: int = 480,
    pitch_bend_range: int = 12,
    velocity: int = 100,
    frame_duration: float = 0.020,
    formant_mode: bool = False,
    stability_threshold: int = 5,
    band_definitions: list[tuple[float, float]] | None = None,
    min_pitch_bend_semitones: float = 1.5,
) -> None:
    """
    Complete pipeline: convert audio file to MIDI file.

    Args:
        audio_path: Input audio file path
        output_path: Output MIDI file path
        bpm: Tempo in beats per minute (default 120)
        ticks_per_beat: MIDI ticks per quarter note (default 480)
        pitch_bend_range: Pitch bend range in semitones (default 12)
        velocity: Fixed note velocity (default 100)
        frame_duration: Analysis frame duration in seconds (default 0.020 = 20ms)
        formant_mode: If True, track multiple peaks per channel for formants
        stability_threshold: Frames needed before formant stable mode activates
        band_definitions: Optional custom frequency band definitions
    """
    from audio_loader import load_audio
    from fft_analyzer import compute_cqt, find_dominant_frequencies, hz_to_midi
    from channel_mapper import ChannelMapper
    from midi_generator import MidiEventGenerator

    print(f"Loading audio: {audio_path}")
    audio, sample_rate = load_audio(audio_path)
    duration = len(audio) / sample_rate
    print(f"Audio loaded: {duration:.2f}s at {sample_rate}Hz")

    # Calculate hop length for 20ms frames
    hop_length = int(sample_rate * frame_duration)
    print(f"Analysis frame rate: {1 / frame_duration:.0f} Hz (hop={hop_length})")

    # Compute CQT for frequency analysis
    # Calculate maximum bins based on Nyquist limit (fmax must be < sample_rate/2)
    # Starting from C1 (~32.7 Hz), each octave doubles frequency
    # Max bins = 12 * log2(Nyquist / fmin)
    import math

    fmin = 32.70  # C1
    nyquist = sample_rate / 2
    max_octaves = math.log2(nyquist / fmin)
    max_bins = int(max_octaves * 12)

    n_bins = min(192, max_bins, int((duration * sample_rate / hop_length) * 0.5))
    n_bins = max(n_bins, 84)  # Minimum 7 octaves

    print(f"Computing CQT with {n_bins} bins (max allowed: {max_bins})...")
    magnitude, frequencies = compute_cqt(
        audio, sample_rate, hop_length=hop_length, n_bins=n_bins
    )

    # Find dominant frequency peaks per frame
    print("Extracting frequency peaks...")
    peaks_per_frame = find_dominant_frequencies(
        magnitude, frequencies, n_peaks=20, formant_mode=formant_mode
    )

    # Initialize channel mapper and MIDI generator
    channel_mapper = ChannelMapper(
        n_channels=15, 
        exclude_channel=10, 
        stability_threshold=stability_threshold,
        band_definitions=band_definitions,
    )
    midi_generator = MidiEventGenerator(
        bpm=bpm,
        ticks_per_beat=ticks_per_beat,
        pitch_bend_range=pitch_bend_range,
        velocity=velocity,
        min_pitch_bend_semitones=min_pitch_bend_semitones,
    )

    # Process each frame
    print("Generating MIDI events...")
    n_frames = len(peaks_per_frame)

    for frame_idx, frame_data in enumerate(peaks_per_frame):
        frame_time = frame_idx * frame_duration

        assignments = channel_mapper.assign_bands_to_channels(frame_data, frame_time)
        channel_mapper.update_channel_states(assignments, frame_time)

        midi_generator.process_frame(assignments, frame_time)

        if (frame_idx + 1) % 100 == 0:
            print(f"  Processed {frame_idx + 1}/{n_frames} frames...")

    # Finalize - turn off all active notes
    midi_generator.finalize(duration)

    # Write MIDI file
    print("Writing MIDI file...")
    writer = MidiFileWriter(bpm=bpm, ticks_per_beat=ticks_per_beat)
    writer.write_events(midi_generator.events, duration)
    writer.save(output_path)

    print(f"Complete! Generated {len(midi_generator.events)} MIDI events.")
