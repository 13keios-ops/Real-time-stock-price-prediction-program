"""Approved local runtime registration, never a credential or arbitrary path."""
import hashlib
import json
from pathlib import Path

SUBDIRECTORY = Path('paper-missions/kr-intraday-candidate-runtime')
VERSION = 'kr-candidate-runtime-v1'


def read_registration(runtime):
    try:
        path = Path(runtime).absolute()/SUBDIRECTORY/'enabled.json'
        if path.resolve() != path or not path.is_file() or path.stat().st_size > 8192 or path.stat().st_nlink != 1:
            return None
        value = json.loads(path.read_text(encoding='utf-8'))
        spec = value['spec']
        if not isinstance(spec, dict):
            return None
        digest = hashlib.sha256(json.dumps(spec, sort_keys=True, ensure_ascii=True,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        if (value.get('enabled') is not True or value.get('spec_hash') != digest
                or spec.get('version') != VERSION or spec.get('symbols') != ['001440', '006800']
                or spec.get('max_gets_per_cycle') != 6 or spec.get('max_gets_per_day') != 2500
                or spec.get('cycle_interval_seconds') != 60 or spec.get('broker_orders_allowed') is not False):
            return None
        return value
    except (ValueError, KeyError, TypeError, OSError):
        return None


def coordinator_for_profile(profile):
    if getattr(profile, 'mode', None) != 'paper':
        return None
    source = getattr(profile, 'token_cache_path', None)
    if not isinstance(source, (str, Path)):
        return None
    cache = Path(source).absolute()
    if cache.parent.name != 'paper' or cache.parent.parent.name != 'kis' or cache.parent.parent.parent.name != 'cache':
        return None
    runtime = cache.parent.parent.parent.parent
    if read_registration(runtime) is None:
        return None
    from app.brokers.kis_paper_coordinator import PaperRequestCoordinator
    return PaperRequestCoordinator(cache.parent/'request-coordinator')
