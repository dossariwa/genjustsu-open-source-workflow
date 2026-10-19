---
title: SAM3 Raw Masks
emoji: 🎭
colorFrom: blue
colorTo: gray
sdk: gradio
sdk_version: 5.49.1
python_version: 3.10.13
app_file: app.py
license: apache-2.0
pinned: false
---

Cloud-only extension of [merve/SAM3-video-segmentation](https://huggingface.co/spaces/merve/SAM3-video-segmentation),
pinned to `d85543326acde4c53740a17859005dcf9d1f5231`.
See `NOTICE` and `UPSTREAM.json` for attribution and exact provenance.

The `/segment_raw` API accepts an uploaded video file and a subject text prompt.
It returns one full-resolution, zero-based binary PNG per input frame in a ZIP.
Inputs must be constant 24 fps, at most 960 pixels per side and **at most 8 seconds**.
Longer videos are rejected, never truncated. An empty detection yields a black
mask; a missing frame result fails the request. Output masks require visual review.

This extension remains inference-unverified until the owner separately validates
its real output. It requires ZeroGPU hosting eligibility and approved access to
`facebook/sam3`. Model weights load only in the cloud Space. Store a restricted
read token with that model's access as the private Space secret `HF_TOKEN`.
Never place tokens in source files or public variables.
