"""Local job CLI. Resume observes saved work and never blindly resubmits."""
import argparse
import json
from pathlib import Path
from config import ROOT, load_env


def parser():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('prepare')
    prepare.add_argument('video')
    prepare.add_argument('--subject', default='person')
    prepare.add_argument('--provider', default='huggingface', choices=['huggingface'])
    prepare.add_argument('--mode', choices=['depth', 'face_mesh', 'depth_mesh'], default='depth')
    for name in ['status', 'repair-rgb', 'resume', 'resume-preparation', 'hd', 'review', 'submit', 'audit', 'prompt']:
        c = sub.add_parser(name)
        c.add_argument('job')
        if name == 'review':
            c.add_argument('--approve', action='store_true')
            c.add_argument('--fingerprint', required=True)
            c.add_argument('--note', required=True)
        if name in {'submit', 'prompt'}:
            c.add_argument('--reference', required=True)
            c.add_argument('--second-reference')
        if name == 'submit':
            c.add_argument('--prompt-file', required=True)
            c.add_argument('--credit-ceiling', type=int)
        if name == 'resume':
            c.add_argument('--hd', action='store_true', help='Explicitly request HD if absent; otherwise collect saved HD')
            c.add_argument('--credit-ceiling', type=int, help='Explicitly approve a previously quoted credit ceiling')
    return p


def main(argv=None):
    load_env()
    p = parser()
    a = p.parse_args(argv)
    if a.command == 'prepare':
        import uuid
        import shutil
        from pipeline import run
        folder = ROOT / 'runs' / uuid.uuid4().hex
        folder.mkdir(parents=True)
        shutil.copy2(a.video, folder / 'upload.mp4')
        print('JOB:', folder.name, flush=True)
        if a.mode == 'face_mesh':
            from face_mesh import run as run_mesh
            run_mesh(folder / 'upload.mp4', folder)
        elif a.mode == 'depth_mesh':
            from face_mesh import run_depth
            run_depth(folder / 'upload.mp4', folder, a.subject, a.provider)
        else:
            run(folder / 'upload.mp4', folder, a.subject, a.provider)
        (folder / 'status.json').write_text(json.dumps({'id': folder.name, 'state': 'done', 'status': 'Full-clip input review required'}))
        return
    if len(a.job) != 32 or any(c not in '0123456789abcdef' for c in a.job):
        p.error('Expected a 32-character local job ID')
    folder = ROOT / 'runs' / a.job
    if not folder.is_dir():
        p.error('Job does not exist')
    from mask_review import state, review
    if a.command == 'status':
        data = {'mask_review': state(folder)}
        for name in ['generation', 'openart-state', 'dreamina-state', 'status']:
            path = folder / (name + '.json')
            data[name] = json.loads(path.read_text()) if path.exists() else None
        print(json.dumps(data, indent=2))
    elif a.command == 'review':
        print(review(folder, a.approve, a.note, a.fingerprint))
    elif a.command == 'resume-preparation':
        from seedance_bridge import resume_preparation
        resume_preparation(folder)
    elif a.command == 'repair-rgb':
        mode_file = folder / 'workflow-mode.json'
        mode = json.loads(mode_file.read_text()).get('mode', 'depth') if mode_file.exists() else 'depth'
        if mode == 'face_mesh':
            p.error('Fast face mesh has no SAM mask; reprepare facial tracking.')
        from raw_masks import segment_raw, clean_border_fragments
        from pipeline import composite
        from audio_workflow import prepare_seedance_video
        meta = json.loads((folder / 'manifest.json').read_text())
        repair = folder / 'rgb-repair'
        repair.mkdir(exist_ok=True)
        masks = clean_border_fragments(segment_raw(folder / 'original.mp4', repair, meta.get('prompt', 'person')))
        composite(folder / 'original.mp4', folder / 'depth.mp4', masks, folder, folder / 'upload.mp4')
        if mode == 'depth_mesh':
            import shutil
            import subprocess
            shutil.copy2(folder / 'composite-silent.mp4', folder / 'depth-composite-silent.mp4')
            subprocess.run([str(ROOT / '.venv-face/bin/python'), str(ROOT / 'mesh_worker.py'), str(folder), '--depth'], check=True)
        prepare_seedance_video(folder)
        (folder / 'mask-review.json').unlink(missing_ok=True)
        meta['mask_method'] = 'SAM 3 on original RGB, preserving depth colors'
        (folder / 'manifest.json').write_text(json.dumps(meta, indent=2))
        print('Repaired. Review the entire clip again; approval cleared.')
    elif a.command in {'audit', 'prompt'}:
        from openai_helper import sample_video_frames, auto_audit_mask_quality, generate_seedance_prompt
        if a.command == 'audit':
            from mask_review import fingerprint
            current = fingerprint(folder)
            result = auto_audit_mask_quality(sample_video_frames(folder / 'composite-silent.mp4', folder / 'audit-samples'))
            if fingerprint(folder) != current:
                raise ValueError('Artifacts changed during the audit. Run a fresh audit.')
            result['fingerprint'] = current
            (folder / 'mask-audit.json').write_text(json.dumps(result, indent=2))
            print(result['findings'])
        else:
            from mask_review import fingerprint
            from seedance_bridge import state_filename
            if (folder / state_filename(folder)).exists():
                p.error('A generation is already saved; its prompt and references are frozen.')
            current = fingerprint(folder)
            frame = sample_video_frames(folder / 'original.mp4', folder / 'scene-samples', 1)[0]
            mode_file = folder / 'workflow-mode.json'
            mode = json.loads(mode_file.read_text()).get('mode', 'depth') if mode_file.exists() else 'depth'
            transcript = folder / 'dialogue.txt'
            prompt = generate_seedance_prompt(frame, [x for x in [a.reference, a.second_reference] if x], transcript.read_text() if transcript.exists() else '', mode)
            if fingerprint(folder) != current:
                raise ValueError('Artifacts changed during prompt generation. Request a fresh suggestion.')
            (folder / 'suggested-prompt.txt').write_text(prompt)
            print(prompt)
    else:
        from seedance_bridge import submit, submit_hd, wait_and_finish, resume_approved, state_filename
        if a.command == 'submit':
            prompt = Path(a.prompt_file).read_text()
            print('Exact creative prompt:\n' + prompt, flush=True)
            submit_id = submit(folder, prompt, a.reference, a.second_reference, credit_ceiling=a.credit_ceiling)
        elif a.command == 'hd':
            submit_id = submit_hd(folder, approved=True)
            folder = folder / 'hd'
        elif a.credit_ceiling is not None:
            if a.hd:
                p.error('HD approval is separate from draft credit approval.')
            submit_id = resume_approved(folder, a.credit_ceiling)
        else:
            if a.hd:
                if not (folder / 'hd' / state_filename(folder / 'hd')).exists():
                    submit_id = submit_hd(folder, approved=True)
                folder = folder / 'hd'
            saved = folder / state_filename(folder)
            if not saved.exists():
                p.error('No saved generation; never resubmit an uncertain request automatically.')
            data = json.loads(saved.read_text())
            submit_id = data.get('history_id') or data.get('submit_id') or data.get('submitId')
            if not submit_id:
                p.error('Saved operation has no generation ID; inspect its provider history before retrying.')
        wait_and_finish(folder, submit_id)
        (folder / 'status.json').write_text(json.dumps({'id': a.job, 'state': 'done', 'status': 'Final preview ready · configured source audio restored'}))
        print(folder / 'final-preview.mp4')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, TimeoutError) as exc:
        raise SystemExit(str(exc)) from None
