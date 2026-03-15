# Turn Audio FFT buckets into MIDI channels
_Note: this is a vibe-coded experiment because I'm too lazy to do all this myself_

This is an attempt to have a python program take any audio file into MIDI similar to WaoN, except instead of just dumping an FFT conversion of all frequencies quantized to nearest piano note on a single channel, this will try to break apart the signal down to 15 buckets and track the frequency changes by using MIDI pitch bend and volume/expression.

The aim of the goal is to have something produce something similar to the following [video](https://www.youtube.com/watch?v=mjnxhay9bF8) which I still do not understand how this was done as no sources have been shared.

This was also an excuse to experiment with agentic AI-assisted coding using Opencode on the M3 Ultra 256GB box with Qwen3-Coder-Next, Qwen3.5-112B-A10B, and GLM-4.7-Flash.


