# AGENTS.md

## Project Overview
This project converts audio files to MIDI format using Constant-Q Transform (CQT) analysis. It breaks audio into 15 frequency bands and tracks them across time, outputting Standard MIDI Files with pitch bend support for smooth frequency transitions.

## Build/Lint/Test Commands

### Prerequisites
- Python 3.10+
- [uv](https://github.com/astral-sh/uv) for fast Python package management

### Running Tests with uv
```bash
# Initialize project (one-time setup)
uv init --no-workspace

# Install dependencies
uv sync

# Run conversion test (generates test audio and converts to MIDI)
uv run python test_conversion.py

# Test frequency peak detection
uv run python test_better_detection.py

# Run a single script directly
uv run python audio_to_midi.py <input_audio> -o output.mid [options]
```

### Running Tests with pip (legacy)
```bash
# Legacy method if uv is not available
pip install -r requirements.txt

# Run conversion test (generates test audio and converts to MIDI)
python test_conversion.py

# Test frequency peak detection
python test_better_detection.py

# Run a single script directly
python audio_to_midi.py <input_audio> -o output.mid [options]
```

### Command-Line Usage
```bash
# Basic conversion
uv run python audio_to_midi.py input.wav -o output.mid

# With custom parameters
uv run python audio_to_midi.py song.mp3 -o song.mid --bpm 120 --velocity 100 --ticks 480
```

## Code Style Guidelines

### General
- **Python version**: 3.10+
- **Line length**: Max 88 characters (use black formatting)
- **Docstrings**: Google-style with Args/Returns/Yields/Raises sections
- **Type hints**: Required for all function signatures using `int`, `float`, `bool`, `str` and collections
- **Imports**: Group as: stdlib, third-party, local

### Imports
```python
# Standard library first
import argparse
import sys
from pathlib import Path

# Third-party libraries
import numpy as np
import librosa
import mido

# Local module imports (relative or absolute)
from fft_analyzer import compute_cqt
from channel_mapper import ChannelMapper
```

### Formatting
- Use **4 spaces** for indentation (no tabs)
- Wrap binary operators after line breaks (`+`, `-`, `*`, `/`, `==`)
- Use blank lines to separate logical code sections
- One statement per line
- Use meaningful variable names with `snake_case`

### Naming Conventions
- **Classes**: `PascalCase` (e.g., `ChannelMapper`, `MidiEventGenerator`)
- **Functions/Methods**: `snake_case` (e.g., `compute_cqt`, `find_dominant_frequencies`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `DEFAULT_BPM`, `MAX_CHANNELS`)
- **Variables**: `snake_case` (e.g., `freq_hz`, `midi_note`, `frame_rate`)
- **MIDI channels**: 1-16 range (channel 10 reserved for percussion)

### Types
- Use `int` for MIDI notes, channel numbers, velocities
- Use `float` for frequencies (Hz), timestamps (seconds), dB values
- Use `np.ndarray` for audio and spectral data
- Use `list[T]` or `dict[K, V]` for collections (avoid `List`, `Dict`)
- Use `tuple[float, float]` for frequency ranges

### Error Handling
```python
# Validate inputs at function boundaries
def validate_input(filepath: str) -> Path:
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    return path

# Use specific exceptions and wrap with context
try:
    input_path = validate_input(args.input_audio)
except FileNotFoundError as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
```

### Constants and Magic Numbers
- Define constants at module level with clear names
- Explain frequency ranges (e.g., `fmin = 32.70  # C1`)
- Document MIDI CC numbers: 7=volume, 11=expression, 6=Data Entry LSB
- Document pitch bend range configuration (CC100/CC101/CC6/CC38)

### File Organization
- One main module per file with clear responsibilities:
  - `audio_loader.py`: Audio I/O and preprocessing
  - `fft_analyzer.py`: CQT/STFT computation and peak detection
  - `channel_mapper.py`: Map frequency bands to MIDI channels
  - `midi_generator.py`: Generate MIDI events with pitch bend
  - `midi_writer.py`: Write Standard MIDI Files
- Test files: `test_*.py` at project root

### Documentation
- Every public function needs a docstring explaining purpose, args, returns
- Explain algorithmic decisions (e.g., why CQT over STFT for audio-to-MIDI)
- Document frequency range calculations and octave mappings
- Comment complex logic: pitch bend interpolation, note triggering thresholds

### MIDI-Specific Conventions
- Note numbers: 0-127 (C-1 to G9)
- MIDI channels: 1-16 (internal) converted to 0-15 for mido
- Velocity: 1-127 (use 64-100 for typical dynamic range)
- Pitch bend: 14-bit value (0-16383), center = 8192
- Pitch bend range: Extended to ±24 semitones via RPN (CC100/101=0, CC6=24)
- Use program_change 79 (ocarina) for all tracks
- Add track_name metadata for organization

### Testing Guidelines
- Generate synthetic test audio with known frequencies
- Verify MIDI file structure (tracks, messages, timing)
- Check edge cases: silence, single notes, frequency glides
- Compare against reference MIDI files when available

## Cursor/Copilot Rules
None configured (no `.cursor/rules/`, `.cursorrules`, or `.github/copilot-instructions.md` found).

## pyproject.toml
Project dependencies are managed using `uv`. The `pyproject.toml` file defines:
- Project metadata (name, version, description)
- Python version requirement (>=3.10)
- Dependencies (librosa, mido, numpy, soundfile)
- Entry point script (`audio-to-midi`)

Run `uv sync` to install dependencies into a virtual environment.

## Common Tasks

### Add new analysis feature
1. Create function in appropriate module (`fft_analyzer.py`, `channel_mapper.py`, etc.)
2. Add comprehensive docstring
3. Use type hints for all parameters and return values
4. Write test in `test_conversion.py` or new `test_*.py`

### Modify MIDI output
1. Update `MidiEventGenerator` for event generation logic
2. Update `MidiFileWriter` for file writing format
3. Verify output with `mido.MidiFile()` inspection

### Fix bugs in peak detection
1. review current threshold logic in `find_dominant_frequencies()`
2. adjust `min_db` and peak filtering criteria
3. Test with `test_better_detection.py`
