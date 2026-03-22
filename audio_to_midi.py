#!/usr/bin/env python3
"""
Audio-to-FFT MIDI Converter

Converts audio files to Standard MIDI Files using Constant-Q Transform analysis.
Maps frequency bands to 15 MIDI channels with extended pitch bend range (±24 semitones).

Usage:
    python audio_to_midi.py <input_audio> -o <output.mid> [options]
"""

import argparse
import sys
from pathlib import Path


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Convert audio files to FFT-equivalent MIDI messages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python audio_to_midi.py input.wav -o output.mid
  python audio_to_midi.py song.mp3 -o song.mid --bpm 100 --velocity 80
  python audio_to_midi.py track.flac -o track.mid --ticks 960

Output:
  Creates a Standard MIDI File (Type 1) with:
  - 15 channels for frequency bands (Channel 10 available as normal channel)
  - Extended pitch bend range (±24 semitones via CC100/CC101/CC6)
  - Continuous frequency tracking with pitch bend transitions
  - Volume control via CC7/CC11
        """,
    )

    parser.add_argument(
        "input_audio",
        type=str,
        help="Input audio file (WAV, MP3, FLAC, AIFF supported)",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=str,
        required=True,
        dest="output_midi",
        help="Output MIDI file path (.mid extension will be added if missing)",
    )

    parser.add_argument(
        "-b",
        "--bpm",
        type=int,
        default=120,
        help="Tempo in beats per minute (default: 120)",
    )

    parser.add_argument(
        "-t",
        "--ticks",
        type=int,
        default=480,
        dest="ticks_per_beat",
        help="MIDI ticks per quarter note for resolution (default: 480)",
    )

    parser.add_argument(
        "-v",
        "--velocity",
        type=int,
        default=100,
        help="Fixed note velocity 1-127 (default: 100). Volume controlled via CC7/CC11",
    )

    parser.add_argument(
        "--pitch-bend-range",
        type=int,
        default=12,
        dest="pitch_bend_range",
        help="Pitch bend range in semitones (default: 12)",
    )

    parser.add_argument(
        "--formant-mode",
        action="store_true",
        help="Enable formant mode for multiple peaks per channel (speech formants)",
    )

    parser.add_argument(
        "--frame-rate",
        type=float,
        default=50.0,
        dest="frame_rate",
        help="Analysis frame rate in Hz (default: 50 = 20ms frames)",
    )

    return parser.parse_args()


def validate_input(filepath: str) -> Path:
    """Validate input file exists and has supported extension."""
    path = Path(filepath)

    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    supported_extensions = {".wav", ".mp3", ".flac", ".aiff", ".aac", ".ogg"}
    if path.suffix.lower() not in supported_extensions:
        print(
            f"Warning: Uncommon extension '{path.suffix}'. Supported: {supported_extensions}"
        )

    return path


def validate_output(filepath: str) -> Path:
    """Validate and normalize output file path."""
    path = Path(filepath)

    # Ensure .mid extension
    if path.suffix.lower() != ".mid":
        path = path.with_suffix(".mid")

    # Check parent directory exists
    if not path.parent.exists():
        raise ValueError(f"Output directory does not exist: {path.parent}")

    return path


def main():
    """Main entry point."""
    args = parse_arguments()

    # Validate inputs
    try:
        input_path = validate_input(args.input_audio)
        output_path = validate_output(args.output_midi)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Validate velocity range
    if not 1 <= args.velocity <= 127:
        print("Error: Velocity must be between 1 and 127", file=sys.stderr)
        sys.exit(1)

    # Import and run conversion
    try:
        from midi_writer import generate_midi_from_audio

        frame_duration = 1.0 / args.frame_rate

        print("=" * 60)
        print("Audio-to-FFT MIDI Converter")
        print("=" * 60)
        print(f"Input:     {input_path}")
        print(f"Output:    {output_path}")
        print(f"BPM:       {args.bpm}")
        print(f"Timebase:  {args.ticks_per_beat} ticks/quarter note")
        print(f"Velocity:  {args.velocity}")
        print(f"Pitch bend: ±{args.pitch_bend_range} semitones (CC100/101/6)")
        print(f"Frame rate: {args.frame_rate:.0f} Hz ({frame_duration * 1000:.0f}ms)")
        print("=" * 60)

        generate_midi_from_audio(
            audio_path=str(input_path),
            output_path=str(output_path),
            bpm=args.bpm,
            ticks_per_beat=args.ticks_per_beat,
            pitch_bend_range=args.pitch_bend_range,
            velocity=args.velocity,
            frame_duration=frame_duration,
            formant_mode=args.formant_mode,
        )

    except ImportError as e:
        print(f"Error: Missing required package - {e}", file=sys.stderr)
        print("\nInstall dependencies with:", file=sys.stderr)
        print("  pip install -r requirements.txt", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error during conversion: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
