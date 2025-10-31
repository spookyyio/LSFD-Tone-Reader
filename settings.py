import os
import json


def get_settings_path(base=None):
    try:
        if base is None:
            base = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        base = os.getcwd()
    return os.path.join(base, 'tonereader_settings.json')


def load_settings():
    """Return last_log path if present and exists, otherwise None."""
    path = get_settings_path()
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                last = data.get('last_log')
                if last and os.path.exists(last):
                    return last
    except Exception:
        pass
    return None


def save_settings(last_log_path: str):
    path = get_settings_path()
    try:
        data = {'last_log': last_log_path}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
    except Exception:
        pass
