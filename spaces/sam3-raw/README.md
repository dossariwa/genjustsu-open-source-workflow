# Cloud SAM3 raw-mask extension

**Deployed to a private ZeroGPU Space; inference remains unverified.** The local
builder prepares a reviewable upload bundle without creating resources, uploading
secrets, installing GPU packages, downloading weights or running inference. Do
not run the generated `app.py` or install this directory's `requirements.txt` on
the local workflow machine.

Deployment status on 2026-10-18: [wosx/genjustsu-sam3-raw](https://huggingface.co/spaces/wosx/genjustsu-sam3-raw)
was created as **private** after explicit authorization. SAM3 model access is
granted. The user's chosen multipurpose token was stored only as the private
`HF_TOKEN` secret. Requested hardware is **`zero-a10g`**, with no paid or CPU
fallback. Current remote commit is
`28a44ff891b02b61c885b764ea1c331d842f4f9e`; the build succeeded and the Space is
**RUNNING**, with both current and requested hardware **`zero-a10g`**.
The existing workflow adapter successfully validated the live `/segment_raw`
schema: `video` is a File, `text_prompt` is a Textbox, and output 0 is the raw-mask
File. No media was uploaded and no prediction was called. The initial build's
`spaces` dependency conflict was corrected to the platform-required `0.51.3`.
The matching local bundle is `/private/tmp/genjustsu-sam3-raw-deploy`.

The workflow accepts videos up to 30 seconds. **This initial endpoint accepts at
most 8 seconds (192 frames at 24 fps)** and rejects longer input. It never silently
truncates. Supporting 30 seconds requires a separate cloud capacity and accuracy
validation; changing a constant is not sufficient.

## Source and local bundle

The patcher uses [merve/SAM3-video-segmentation at
`d85543326acde4c53740a17859005dcf9d1f5231`](https://huggingface.co/spaces/merve/SAM3-video-segmentation/tree/d85543326acde4c53740a17859005dcf9d1f5231).
The exact upstream `app.py` SHA-256 is
`52eb1e719cc1c712f1dfe6b2bc0c47c8e6b49e2a9f510d1ea65dfa8174992ef0`.
Any byte drift aborts before creating an output directory. The original source
and attribution remain intact except for two anchored edits: reject truncation,
and register the raw endpoint before launching Gradio. No upstream UI is vendored
in this repository. `NOTICE` and `LICENSE` retain Apache 2.0 attribution; the gated
SAM3 model has separate terms and access requirements.

From the repository root, build into a **new** directory:

```sh
.venv/bin/python spaces/sam3-raw/patch_space.py --output /tmp/sam3-raw-upload
.venv/bin/python -m unittest discover -s tests -p test_raw_space_package.py -v
```

The builder downloads only three pinned text files from the public Space:
`app.py` (approximately 53 KB), `uv.lock` (395 KB), and `requirements.txt`.
It verifies every SHA-256 from `UPSTREAM.json`, including both dependency files,
before writing anything. For an offline build, add all three options:
`--source-app /path/to/app.py --source-lock /path/to/uv.lock --source-requirements /path/to/requirements.txt`.
The same checks still apply. Existing output directories are never overwritten.
Syntax is checked with `ast.parse`, without importing or executing the app.

The output contains `app.py`, `raw_endpoint.py`, `requirements.txt`, `README.md`,
`UPSTREAM.json`, `NOTICE` and `LICENSE`. Review these exact files before upload.
Direct Python dependencies are pinned to the upstream lock's versions except
`spaces==0.51.3`, which the current ZeroGPU builder explicitly requires. The cloud
build exposed and confirmed this requirement. Upstream
has different Transformers pins in `requirements.txt` and `uv.lock`; this package
explicitly retains the full `requirements.txt` commit
`c3fb1b1a6ca1102f62b139c83a088a97e5a55477`, the Space's Gradio build input.
Its lock has `69f003696b55de75b7f18888c03111909a7cd537` instead. The generated
requirements replace that ambiguity; the replacement cloud build succeeded.
Transitive dependencies and the model repository are not frozen by this package.

## Endpoint contract

`/segment_raw(video, text_prompt)` accepts a Gradio **File** and **Textbox** and
returns one **File**, labelled **Raw masks ZIP**. File input keeps the uploaded
video bytes unchanged instead of applying Gradio Video preprocessing. The client
already supports this schema. It sends normalized 24 fps input at no more than
960 pixels per side. PyAV verifies decoded frame count, dimensions and consecutive
timestamps before calling the upstream model functions.

The input is passed directly to the original RGB decoder. Colored depth stays
colored depth; an original RGB fallback stays original RGB. The helper does not
recolor input, infer masks from overlays, resize masks, or drop frames. It invokes
the existing `@spaces.GPU` text-prompt and propagation functions, then unions their
actual per-object binary masks into one full-resolution `mask_000000.png` per
source frame. Every PNG contains only 0/255 pixels; the ZIP has no other files.

An explicit empty detection dictionary produces an all-zero PNG. A missing frame
index, wrong geometry or nonbinary result fails the whole request. Initial
frame-0 prompt masks are cleared before propagation so they cannot conceal a
missing result or a disappeared object. The local workflow retains empty-mask
diagnostics and retries on original RGB as needed. Full-clip visual review and
the workflow's approval binding remain required after any successful inference.

Offline unit tests cover the real 192/193-frame duration boundary, malformed
timestamps, RGB passthrough, mask union/geometry, empty versus missing results,
drift rejection and non-overwriting bundle creation. They load no SAM models.

## Deployment procedure and verification

The current deployment is already created and verified as described above.
Steps 4–5 record how the initial deployment was made; do not duplicate it again.
For a later update, inspect the same destination, preserve its private visibility
and ZeroGPU hardware, and guard any commit with its freshly read current SHA.

1. Approved access to [`facebook/sam3`](https://huggingface.co/facebook/sam3) was
   verified with the saved replacement token. Before a later deployment, recheck
   authentication and model access with the read-only
   `HfApi(token=...).auth_check('facebook/sam3', repo_type='model', write=False)`.
   Read metadata only; do not test by downloading weights locally.
2. Confirm personal-account ZeroGPU eligibility. Current [ZeroGPU
   documentation](https://huggingface.co/docs/hub/spaces-zerogpu) permits up to two
   free personal Spaces for accounts in good standing with verified email and
   more than 30 days of account age. The account checked during setup is older
   than 30 days and now has PRO. The server accepted the private Space with
   explicitly selected ZeroGPU hardware. Free users
   have a daily GPU quota; do not enable paid hardware, prepaid extensions or
   auto-purchase. If free eligibility is denied, stop and report it.
3. The local deployment token needs `repo.write` for the owner's namespace. The
   deployment credential must declare that permission. A separate fine-grained
   **read** token would suffice for the Space runtime. The user explicitly chose
   the project's multipurpose full-access token for this private Space instead.
   The runtime token's account must itself have gated access. Store it only as a
   private Space secret called **`HF_TOKEN`**. Do not publish the broad write
   token in source, variables, command arguments or logs. The project's local
   `HF_ACCESS_TOKEN` authenticates later private-Space client calls and must have
   access to that Space; the alias is separate from the cloud runtime secret.
4. Once deployment and secret transfer are authorized, duplicate the source into
   the user's namespace as **private**, explicitly choosing **`zero-a10g`**. The
   installed SDK supports `HfApi.duplicate_repo`, not `duplicate_space`:

   ```python
   from huggingface_hub import HfApi
   from huggingface_hub.hf_api import SpaceHardware

   # Obtain deploy_token and the chosen runtime_token privately in memory.
   api = HfApi(token=deploy_token)
   upstream = "merve/SAM3-video-segmentation"
   pinned = "d85543326acde4c53740a17859005dcf9d1f5231"
   assert api.repo_info(upstream, repo_type="space").sha == pinned
   result = api.duplicate_repo(
       upstream, to_id=space_id, repo_type="space", private=True,
       exist_ok=False, space_hardware=SpaceHardware.ZERO_A10G,
       space_secrets=[{"key": "HF_TOKEN", "value": runtime_token}],
   )
   ```

   `space_id` is a stable, user-selected `owner/name`. Duplication preserves Git
   history and examples server-side, so media is not downloaded locally. The SDK
   has no duplication revision argument. Check the source HEAD first and the
   duplicate HEAD afterwards; abort on drift instead of silently mixing versions.
   If `result.files_copy_pending` is true, wait for server-side file copying to
   finish before building. Never retry an uncertain duplicate blindly: inspect
   the same destination first. Do not fall back to paid or CPU hardware.
5. Upload exactly the reviewed bundle as a single commit using the guarded API:

   ```python
   from pathlib import Path
   from huggingface_hub import CommitOperationAdd

   head = api.repo_info(space_id, repo_type="space").sha
   assert head == pinned
   bundle = Path("/tmp/sam3-raw-upload")
   names = ("app.py", "raw_endpoint.py", "requirements.txt", "README.md",
            "UPSTREAM.json", "NOTICE", "LICENSE")
   operations = [CommitOperationAdd(path_in_repo=name, path_or_fileobj=bundle / name)
                 for name in names]
   api.create_commit(space_id, repo_type="space", operations=operations,
                     parent_commit=head,
                     commit_message="feat: expose aligned raw sam3 masks")
   ```

   Keep the duplicate's upstream example assets. The generated README pins
   Gradio 5.49.1 and Python 3.10.13; the cloud build alone installs GPU dependencies
   and downloads the gated weights. See the official [Spaces management
   guide](https://huggingface.co/docs/huggingface_hub/guides/manage-spaces) for secret,
   commit and hardware interfaces. A failed build does not authorize a paid upgrade.
6. Read `api.get_space_runtime(space_id)` and verify current/requested hardware
   are ZeroGPU and stage is running. Inspect the live Gradio schema without
   calling `predict`. Configure locally:

   ```ini
   HF_SAM_SPACE=owner/your-raw-sam3-space
   HF_SAM_API_NAME=/segment_raw
   ```

   Then run `.venv/bin/python -c 'from raw_masks import inspect_endpoint; inspect_endpoint()'`
   and `.venv/bin/python doctor.py --require-keys`. Schema, build and credential
   success establish configured readiness only. They do not prove correct masks.
7. Only after inference use is separately authorized, validate a short real clip,
   RGB fallback, cuts and the full eight-second boundary. Inspect every output
   frame and its composite. The initial package has not passed those cloud tests.

The private Space and its private secret were created only after explicit user
authorization. Authentication and approved model access were verified. No media
was submitted, no inference ran, and no paid compute was provisioned.
