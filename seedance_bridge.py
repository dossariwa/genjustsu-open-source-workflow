"""Generation routing: OpenArt for new work; legacy Dreamina collection only.

Importing this facade never contacts a provider. Saved legacy requests cannot be
migrated into a new paid generation or resumed through the active provider.
"""
import json
from pathlib import Path

from openart_bridge import OpenArtError as ProviderError, CreditApprovalRequired, RecoveryRequired


def state_filename(folder):
    """Return the existing provider state basename, defaulting to OpenArt."""
    folder = Path(folder)
    if (folder / 'openart-state.json').exists():
        return 'openart-state.json'
    if (folder / 'dreamina-state.json').exists():
        return 'dreamina-state.json'
    return 'openart-state.json'


def _require_active_provider(folder):
    folder = Path(folder)
    if (folder / 'dreamina-state.json').exists():
        raise ProviderError('This job contains saved legacy provider work. Only collection is supported; prepare a new job for an explicitly approved OpenArt generation.')
    response = folder / 'seedance-response.json'
    if response.exists():
        try:
            response_data = json.loads(response.read_text())
            active_data = json.loads((folder / 'openart-state.json').read_text())
        except (ValueError, OSError):
            raise ProviderError('Saved provider response has no readable OpenArt state. Inspect the original operation before any new submission.') from None
        if not (isinstance(response_data, dict) and response_data.get('provider') == 'openart'
                and isinstance(active_data, dict) and active_data.get('provider') == 'openart'):
            raise ProviderError('This job contains a legacy or unknown provider response. It cannot be resubmitted through OpenArt.')
    saved = folder / 'generation.json'
    if saved.exists():
        try:
            metadata = json.loads(saved.read_text())
        except (ValueError, OSError):
            raise ProviderError('Saved generation metadata is unreadable. Inspect the existing operation before any new submission.') from None
        provider = metadata.get('provider') if isinstance(metadata, dict) else None
        if provider != 'openart':
            raise ProviderError('This saved generation belongs to a legacy or unknown provider. It cannot be resubmitted through OpenArt.')


def capabilities():
    from openart_bridge import capabilities as active_capabilities
    result = dict(active_capabilities())
    # Provider support alone cannot enable an unimplemented approval flow.
    result.update(video_hd_supported=False,
                  hd_detail='OpenArt draft HD completion requires its saved upgrade action and a separately approved quote. This workflow has not enabled that action; the draft is preserved.',
                  detail='OpenArt Seedance 2.5 Draft adapter configured. Doctor verifies the account and model without generation; each draft needs an approved credit quote.')
    return result


def submit(folder, prompt, sirio, tein=None, status=print, credit_ceiling=None):
    _require_active_provider(folder)
    from openart_bridge import submit as active_submit
    return active_submit(folder, prompt, sirio, tein, status, credit_ceiling)


def resume_preparation(folder, status=print):
    _require_active_provider(folder)
    from openart_bridge import resume_preparation as active_resume
    return active_resume(folder, status)


def resume_approved(folder, credit_ceiling, status=print):
    _require_active_provider(folder)
    from openart_bridge import resume_approved as active_resume
    return active_resume(folder, credit_ceiling, status)


def wait_and_finish(folder, request_id, status=print):
    if state_filename(folder) == 'dreamina-state.json':
        from dreamina_bridge import wait_and_finish as legacy_collect, DreaminaError
        from dreamina_bridge import CreditApprovalRequired as LegacyCreditApprovalRequired
        try:
            return legacy_collect(folder, request_id, status)
        except LegacyCreditApprovalRequired:
            raise ProviderError('The saved Dreamina draft was never submitted. Only existing submitted work can be collected; legacy spending cannot be resumed.') from None
        except DreaminaError as exc:
            raise ProviderError(str(exc)) from None
    _require_active_provider(folder)
    from openart_bridge import wait_and_finish as active_collect
    return active_collect(folder, request_id, status)


def submit_hd(folder, approved=False):
    if not approved:
        raise ValueError('Explicit HD upgrade approval is required.')
    _require_active_provider(folder)
    raise ProviderError('OpenArt HD completion requires a saved draft upgrade action and a separately approved quote. This workflow has not enabled that action; no upgrade or replacement generation was submitted.')
