# Linux Mint Audio Device Fix

## What Was Done
Fixed a one-way LAN voice-chat failure where Linux Mint could hear macOS audio but did not transmit microphone audio back to macOS.

The client audio engine no longer assumes every machine can open its default microphone and speaker at 16 kHz mono PCM. On startup it now enumerates usable PyAudio input and output devices, prefers each device's native/default rate, then falls back to common 48 kHz / 44.1 kHz rates and finally the app's 16 kHz network rate. If a device runs at a non-16 kHz rate, the client resamples at the boundary using a stateful in-process mono 16-bit linear resampler: microphone input is converted to the 16 kHz wire format before sending, and received 16 kHz mixed audio is converted to the local speaker rate before playback. Keeping resampler state across 20 ms chunks avoids repeated interpolation resets that can sound noisy on Linux.

Playback startup is no longer blocked by microphone startup. If the speaker/output stream opens but the microphone does not, the app starts in listen-only mode and shows a diagnostic warning instead of silently disabling receive audio. The existing UI diagnostic line now reports audio startup failures when no usable microphone or speaker is found. The logs include selected device indexes, device names, sample rates, failed candidates, capture/send counters, playback/write counters, server receive/send counters, and peak/RMS levels, which should make Linux Mint/PulseAudio/ALSA setup problems visible during LAN tests.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `client/features/audio_engine.py` | Modified | Add PyAudio device probing, sample-rate fallback, stateful capture/playback resampling, and detailed device/level logs. |
| `client/ui/screen_share_widget.py` | Modified | Keep listen-only microphone warnings visible while receive audio remains active. |
| `server/features/audio_mixer.py` | Modified | Add per-room receive/send counters and signal-level logs for LAN audio routing diagnostics. |
| `tests/test_audio_engine.py` | Created | Cover audio frame sizing, candidate-rate helper behavior, stateful resampling, and signal-level diagnostics. |
| `tests/test_audio_mixer.py` | Modified | Cover mixer receive/send diagnostic counters while preserving personalised audio routing behavior. |
| `docs/14_linux_mint_audio_fix.md` | Created | Document the Linux Mint LAN audio fix and verification steps. |

## Why It Matters
Linux audio devices often expose microphone and speaker streams through PulseAudio/ALSA at 44.1 kHz or 48 kHz. Opening them directly at 16 kHz can fail, and writing 16 kHz frames into a different-rate output path can sound noisy or distorted. Negotiating a real device format and resampling keeps the network protocol stable while letting each operating system use an audio rate it supports. Keeping receive audio independent from microphone capture also prevents one user's local input-device problem from breaking their ability to hear the other user.

This app is a PyQt/PyAudio desktop client, not a browser/WebRTC client. Browser APIs such as `getUserMedia`, audio constraints, ICE candidates, and `RTCPeerConnection` are not part of this codebase.

## Manual LAN Verification
1. On Linux Mint, confirm the microphone is available in system sound settings and is not muted.
2. Start the app from a terminal on Linux Mint so PyAudio logs are visible.
3. Join the same regular room from macOS and Linux Mint.
4. Check the Linux terminal for `Audio input preflight succeeded` and `Audio capture sent`.
5. Check the macOS terminal for `Audio playback queue received` and `Audio playback wrote`.
6. Check the server terminal for `received ... audio frames` from the Linux user and `sent ... mixed audio frames` to the macOS user.
7. Speak from Linux Mint and confirm macOS receives audio.
8. Speak from macOS and confirm Linux Mint receives audio without severe noise.
9. Toggle Mute on Linux Mint and confirm macOS stops hearing Linux audio; unmute and confirm transmission resumes.
