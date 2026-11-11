"""
What KPI's screens need before they offer the box's AI, beyond NLP_BACKEND=local:

- Automatic transcription and translation for every user (Constance's
  ASR_MT_INVITEE_USERNAMES = '*'). Empty, the default, the API still works but
  Processing only offers to type a transcript or translation by hand.
- The language tables: without them the language pickers in Processing find nothing.
  Each language is marked as offered by Google's services, which is what the screens
  look for; with NLP_BACKEND=local the requests go to the box's models instead.

Re-running is safe. Run ON THE BOX:

    docker exec -i kobofe-kpi-1 python manage.py shell < kpi/ai-setup.py

kobo-setup.py runs it after starting Kobo with local AI (the KPI image or the backport).
"""
from constance import config

from kobo.apps.languages.models.language import Language, LanguageRegion
from kobo.apps.languages.models.transcription import (
    TranscriptionService,
    TranscriptionServiceLanguageM2M,
)
from kobo.apps.languages.models.translation import (
    TranslationService,
    TranslationServiceLanguageM2M,
)

# (code, name): the languages measured or spot-checked on the box (README, Results)
LANGUAGES = [
    ('en', 'English'),
    ('fr', 'French'),
    ('es', 'Spanish'),
    ('pt', 'Portuguese'),
    ('sw', 'Swahili'),
    ('ar', 'Arabic'),
]

mt, _ = TranslationService.objects.get_or_create(code='goog', defaults={'name': 'Google'})
asr, _ = TranscriptionService.objects.get_or_create(code='goog', defaults={'name': 'Google'})
for code, name in LANGUAGES:
    language, created = Language.objects.get_or_create(
        code=code, defaults={'name': name, 'featured': True}
    )
    TranslationServiceLanguageM2M.objects.get_or_create(language=language, service=mt)
    # Transcription is offered per region; one with the bare code stands for them all
    region, _ = LanguageRegion.objects.get_or_create(
        code=code, defaults={'language': language, 'name': name}
    )
    TranscriptionServiceLanguageM2M.objects.get_or_create(
        language=language, service=asr, region=region
    )
    print(('added' if created else 'kept'), code, name)

config.ASR_MT_INVITEE_USERNAMES = '*'
print('automatic transcription and translation: everyone')
