import os
from django.conf import settings
from django.conf.locale import LANG_INFO

# Minimal metadata for languages Django doesn't know about by default.
# Keys must match the codes produced in the translations/ folder (e.g., 'tcy').
CUSTOM_LANG_INFO = {
    # Tulu (ISO 639-3: tcy)
    'tcy': {
        'name': 'Tulu',
        'name_local': 'Tulu',  # Keep neutral to avoid script inaccuracies
        'bidi': False,
        'code': 'tcy',
    },
    # Kalmyk (already present in some Django versions, keep for safety)
    'xal': {
        'name': 'Kalmyk',
        'name_local': 'Хальмг',
        'bidi': False,
        'code': 'xal',
    },
    # Serbian variant code present in translations; map minimally so templates don’t break
    'sr-ec': {
        'name': 'Serbian (Ekavian)',
        'name_local': 'Srpski (Ekavski)',
        'bidi': False,
        'code': 'sr-ec',
    },
}

def _ensure_language_registered(lang_code: str):
    """Ensure lang_code exists in Django's LANG_INFO to prevent KeyError in templates.

    If Django doesn't know the code, add a minimal entry from CUSTOM_LANG_INFO
    or a generic fallback using the code as the display name.
    """
    if lang_code in LANG_INFO:
        return
    info = CUSTOM_LANG_INFO.get(lang_code)
    if info is None:
        info = {
            'name': lang_code,
            'name_local': lang_code,
            'bidi': False,
            'code': lang_code,
        }
    LANG_INFO[lang_code] = info

def get_available_languages():
    locale_dir = os.path.join(settings.BASE_DIR, 'translations')
    languages = []

    if os.path.exists(locale_dir):
        for file in os.listdir(locale_dir):
            # Drop the ".json" extension
            file = file.split('.')[0]
            if file == 'qqq':  # Skip the message documentation folder
                continue
            # Before including, make sure Django knows about this language code
            _ensure_language_registered(file)
            languages.append((file, file))  # Append the language code and name
    else:
        languages = [('en', 'English')]
                
    return languages

def add_custom_languages():
    # Backward compatibility: explicitly register any custom languages
    for code, info in CUSTOM_LANG_INFO.items():
        if code not in LANG_INFO:
            LANG_INFO[code] = info