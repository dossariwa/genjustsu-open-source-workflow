"""Materialize a cloud upload bundle without importing SAM or downloading weights.

SPDX-License-Identifier: Apache-2.0
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
from urllib.request import urlopen

PACKAGE = Path(__file__).resolve().parent
UPSTREAM = json.loads((PACKAGE / "UPSTREAM.json").read_text())

TRIM_BLOCK = '''    if len(frames) > max_frames_allowed:
        frames = frames[:max_frames_allowed]
        trimmed_note = f" (trimmed to {int(MAX_SECONDS)}s = {len(frames)} frames)"
        if isinstance(info, dict):
            info["num_frames"] = len(frames)
'''
REJECT_BLOCK = '''    if not fps_in or len(frames) / fps_in > MAX_SECONDS:
        raise gr.Error("Supply valid video of at most 8 seconds; truncation is forbidden.")
'''
LAUNCH = "demo.queue(api_open=False).launch()"
REGISTER = '''# Added by the SAM3 raw-mask extension; see NOTICE and UPSTREAM.json.
from raw_endpoint import install_raw_endpoint

install_raw_endpoint(demo, AppState, init_video_session, on_text_prompt, propagate_masks)
demo.queue(api_open=False).launch()
'''


def patch_source(source):
    """Reject any upstream byte drift, then apply exactly two anchored changes."""
    if hashlib.sha256(source).hexdigest() != UPSTREAM["app_sha256"]:
        raise ValueError("Upstream app.py checksum mismatch; refusing to patch source drift.")
    original = source.decode("utf-8")
    if original.count(TRIM_BLOCK) != 1 or original.count(LAUNCH) != 1:
        raise ValueError("Pinned upstream patch anchors changed; refusing to continue.")
    patched = original.replace(TRIM_BLOCK, REJECT_BLOCK).replace(LAUNCH, REGISTER.rstrip())
    ast.parse(patched)  # Syntax validation only; never execute model-loading code.
    return patched


def build_bundle(output, source=None, dependency_lock=None, upstream_requirements=None):
    """Fetch three pinned source text files, or verify all three offline copies."""
    output = Path(output)
    if output.exists():
        raise ValueError("Output already exists; choose a new directory. Nothing was overwritten.")
    def fetch(name):
        url = (f"https://huggingface.co/spaces/{UPSTREAM['repo_id']}/raw/"
               f"{UPSTREAM['revision']}/{name}")
        with urlopen(url, timeout=30) as response:
            content = response.read(1_000_001)
        if len(content) > 1_000_000:
            raise ValueError("Unexpected upstream source size; refusing to continue.")
        return content

    if source is None:
        if dependency_lock is not None or upstream_requirements is not None:
            raise ValueError("Offline verification requires all three upstream source files.")
        source = fetch("app.py")
        dependency_lock = fetch("uv.lock")
        upstream_requirements = fetch("requirements.txt")
    patched = patch_source(source)
    for name, content, expected in (
        ("uv.lock", dependency_lock, UPSTREAM["dependency_lock_sha256"]),
        ("requirements.txt", upstream_requirements, UPSTREAM["upstream_requirements_sha256"]),
    ):
        if content is None or hashlib.sha256(content).hexdigest() != expected:
            raise ValueError(f"Upstream {name} checksum mismatch; refusing dependency drift.")
    files = {name: (PACKAGE / name).read_bytes() for name in
             ("raw_endpoint.py", "requirements.txt", "UPSTREAM.json", "NOTICE", "LICENSE")}
    files["README.md"] = (PACKAGE / "SPACE_README.md").read_bytes()
    files["app.py"] = patched.encode("utf-8")
    output.mkdir()  # Exclusive directory; parent must already exist.
    try:
        for name, content in files.items():
            (output / name).write_bytes(content)
    except BaseException:
        shutil.rmtree(output)
        raise
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="New local bundle directory")
    parser.add_argument("--source-app", type=Path, help="Optional offline pinned upstream app.py")
    parser.add_argument("--source-lock", type=Path, help="Offline pinned upstream uv.lock")
    parser.add_argument("--source-requirements", type=Path, help="Offline pinned upstream requirements.txt")
    args = parser.parse_args()
    if any((args.source_app, args.source_lock, args.source_requirements)) and not all(
            (args.source_app, args.source_lock, args.source_requirements)):
        parser.error("Offline builds require --source-app, --source-lock and --source-requirements together.")
    source = args.source_app.read_bytes() if args.source_app else None
    lock = args.source_lock.read_bytes() if args.source_lock else None
    requirements = args.source_requirements.read_bytes() if args.source_requirements else None
    try:
        result = build_bundle(args.output, source, lock, requirements)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Bundle not created: {exc}\n")
    print(f"Local cloud-only bundle: {result.resolve()}")
    print("No deployment, secret upload, model download or inference was performed.")


if __name__ == "__main__":
    main()
