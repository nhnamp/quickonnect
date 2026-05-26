# Testing Guide

## What Was Done
Created a concise Vietnamese testing guide for the three demo paths: testing on one machine, testing over LAN, and testing over ngrok with one free TCP tunnel. The guide focuses on the commands to run, the host/port values to enter, and the basic audio test flow.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `testing.md` | Created / Shortened | User-facing Vietnamese quick guide for same-machine, LAN, and ngrok testing before the demo. |
| `docs/22_testing_guide.md` | Created | Documents this documentation step. |

## Why It Matters
The demo setup has several modes and the ngrok free-plan path differs from the normal load-balancer architecture. A dedicated testing guide reduces setup mistakes, especially around which host and port to enter on each machine.
