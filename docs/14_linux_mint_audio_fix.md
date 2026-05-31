# Linux Mint Audio Device Fix

## What Was Done
Fixed a one-way LAN voice-chat failure where Linux Mint could hear macOS audio but did not transmit microphone audio back to macOS.

The client audio engine no longer assumes every machine can open its default microphone and speaker at 16 kHz mono PCM. On startup it now enumerates usable PyAudio input and output devices, tries the app network rate first, then falls back to each device's native/default rate and common 48 kHz / 44.1 kHz rates. If a device runs at a non-16 kHz rate, the client resamples at the boundary using an in-process mono 16-bit linear resampler: microphone input is converted to the 16 kHz wire format before sending, and received 16 kHz mixed audio is converted to the local speaker rate before playback.

The existing UI diagnostic line now reports audio startup failures when no usable microphone or speaker is found. The logs include selected device indexes, device names, sample rates, and failed candidates, which should make Linux Mint/PulseAudio/ALSA setup problems visible during LAN tests.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `client/features/audio_engine.py` | Modified | Add PyAudio device probing, sample-rate fallback, capture/playback resampling, and detailed device logs. |
| `tests/test_audio_engine.py` | Created | Cover audio frame sizing and candidate-rate helper behavior. |
| `docs/14_linux_mint_audio_fix.md` | Created | Document the Linux Mint LAN audio fix and verification steps. |

## Why It Matters
Linux audio devices often expose microphone and speaker streams through PulseAudio/ALSA at 44.1 kHz or 48 kHz. Opening them directly at 16 kHz can fail, and writing 16 kHz frames into a different-rate output path can sound noisy or distorted. Negotiating a real device format and resampling keeps the network protocol stable while letting each operating system use an audio rate it supports.

This app is a PyQt/PyAudio desktop client, not a browser/WebRTC client. Browser APIs such as `getUserMedia`, audio constraints, ICE candidates, and `RTCPeerConnection` are not part of this codebase.

## Manual LAN Verification
1. On Linux Mint, confirm the microphone is available in system sound settings and is not muted.
2. Start the app from a terminal on Linux Mint so PyAudio logs are visible.
3. Join the same regular room from macOS and Linux Mint.
4. Check the Linux terminal for `Audio preflight succeeded` and selected input/output device names.
5. Speak from Linux Mint and confirm macOS receives audio.
6. Speak from macOS and confirm Linux Mint receives audio without severe noise.
7. Toggle Mute on Linux Mint and confirm macOS stops hearing Linux audio; unmute and confirm transmission resumes.
