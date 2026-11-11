"""
Unit tests for propose.py: a template from a form with every question type, Contacts and
Cases, fields EspoCRM has already, and previews:

    PYTHONPATH=.:tests python3 -m unittest discover -s tests
"""
import unittest

import bridge
import propose

EVERY = {
    'settings': {'form_title': 'Every question'},
    'translations': ['English (en)', 'Français (fr)'],
    'survey': [
        {'type': 'start', 'name': 'start'}, {'type': 'end', 'name': 'end'}, {'type': 'today', 'name': 'today'},
        {'type': 'deviceid', 'name': 'deviceid'},
        {'type': 'note', 'name': 'intro', 'label': ['Hello', 'Bonjour']},
        {'type': 'text', 'name': 'site_name', 'label': ['Site name', 'Nom du site'], 'required': True},
        {'type': 'text', 'name': 'notes', 'label': ['Notes', 'Notes'], 'appearance': 'multiline'},
        {'type': 'begin_group', 'name': 'counts'},
        {'type': 'integer', 'name': 'people', 'label': ['How many people?', 'Combien ?']},
        {'type': 'decimal', 'name': 'litres_per_day', 'label': ['Litres', 'Litres']},
        {'type': 'range', 'name': 'score', 'label': ['Score', 'Score']},
        {'type': 'end_group'},
        {'type': 'date', 'name': 'visit_date', 'label': ['Date', 'Date']},
        {'type': 'datetime', 'name': 'seen_at', 'label': ['When', 'Quand']},
        {'type': 'time', 'name': 'opening_time', 'label': ['Opens', 'Ouvre']},
        {'type': 'select_one', 'select_from_list_name': 'yn', 'name': 'working', 'label': ['Working?', 'Marche ?']},
        {'type': 'select_multiple', 'select_from_list_name': 'risk', 'name': 'risks', 'label': ['Risks', 'Risques']},
        {'type': 'select_one_from_file', 'file': 'sites.csv', 'name': 'site', 'label': ['Site', 'Site']},
        {'type': 'geopoint', 'name': 'location', 'label': ['Where', 'Où']},
        {'type': 'geotrace', 'name': 'pipe', 'label': ['Pipe', 'Tuyau']},
        {'type': 'geoshape', 'name': 'area', 'label': ['Area', 'Zone']},
        {'type': 'barcode', 'name': 'meter', 'label': ['Meter', 'Compteur']},
        {'type': 'acknowledge', 'name': 'consent', 'label': ['I agree', "J'accepte"]},
        {'type': 'rank', 'name': 'priorities', 'label': ['Rank', 'Classer']},
        {'type': 'calculate', 'name': 'total', 'calculation': '${people} * 2'},
        {'type': 'hidden', 'name': 'source'},
        {'type': 'image', 'name': 'photo', 'label': ['Photo', 'Photo']},
        {'type': 'audio', 'name': 'voice', 'label': ['Voice', 'Voix']},
        {'type': 'file', 'name': 'report', 'label': ['Report', 'Rapport']},
        {'type': 'begin_repeat', 'name': 'household'},
        {'type': 'text', 'name': 'member', 'label': ['Member', 'Membre']},
        {'type': 'end_repeat'},
    ],
    'choices': [
        {'list_name': 'yn', 'name': 'yes', 'label': ['Yes', 'Oui']},
        {'list_name': 'yn', 'name': 'no', 'label': ['No', 'Non']},
        {'list_name': 'risk', 'name': 'flood', 'label': ['Flood', 'Inondation']},
        {'list_name': 'risk', 'name': 'fire', 'label': ['Fire', 'Feu']},
    ],
}


def mapping(p):
    return {f['kobo']: (f['espo'], f.get('type')) for f in bridge.parse_template(p['template'])['field']
            if f.get('kobo')}


class EveryType(unittest.TestCase):
    def setUp(self):
        self.p = propose.propose(EVERY, 'CSite', team='Response: North', notify=['lead'])
        self.t = bridge.parse_template(self.p['template'])

    def test_types(self):
        self.assertEqual(mapping(self.p), {
            'end': ('finishedAt', 'datetime'), 'notes': ('notes', 'text'), 'people': ('people', 'int'),
            'litres_per_day': ('litresPerDay', 'float'), 'score': ('score', 'float'), 'visit_date': ('visitDate', 'date'),
            'seen_at': ('seenAt', 'datetime'), 'opening_time': ('openingTime', 'varchar'),
            'working': ('working', 'enum'), 'risks': ('risks', 'multiEnum'), 'site': ('site', 'varchar'),
            'location': ('location', 'varchar'), 'pipe': ('pipe', 'text'), 'area': ('area', 'text'),
            'meter': ('meter', 'varchar'), 'consent': ('consent', 'varchar')})

    def test_name_media_route(self):
        rec = self.t['record']
        self.assertEqual((rec['name'], rec['required'], rec['media']), ('{site_name}', ['site_name'], 'koboFiles'))
        files = [f for f in self.t['field'] if f['espo'] == 'koboFiles']
        self.assertEqual(files, [{'espo': 'koboFiles', 'type': 'attachmentMultiple', 'label': 'Files from Kobo'}])
        self.assertEqual(self.t['route'], [{'team': 'Response: North', 'notify': ['lead']}])

    def test_left_out_with_reasons(self):
        left = dict(self.p['left_out'])
        self.assertEqual(set(left), {'start', 'today', 'deviceid', 'intro', 'priorities', 'total', 'source', 'household'})
        self.assertIn('repeat', left['household'])
        self.assertTrue(any('household' in w for w in self.p['warnings']))
        self.assertNotIn('member', mapping(self.p))  # inside the repeat
        self.assertIn('# Left out: total (calculated', self.p['template'])

    def test_labels_and_rows(self):
        labels = {f['kobo']: f.get('label') for f in self.t['field'] if f.get('kobo')}
        self.assertEqual((labels['litres_per_day'], labels['visit_date'], labels['location']),
                         ('Litres per day', 'Visit date', 'Location (Kobo geopoint)'))
        fr = propose.propose(EVERY, 'CSite', language='fr_FR')
        rows = {r['question']: r for r in fr['fields']}
        self.assertEqual(rows['people']['asked'], 'Combien ?')
        self.assertEqual(rows['photo']['espo'], '(attachments)')

    def test_geopoint_also_as_numbers(self):
        loc = next(f for f in self.t['field'] if f['kobo'] == 'location')
        self.assertEqual((loc['latitude'], loc['longitude']), ('locationLatitude', 'locationLongitude'))
        # An entity with latitude and longitude floats (kobo-espo's Site) gets those
        have = propose.propose(EVERY, 'CSite', existing={'latitude': 'float', 'longitude': 'float'})
        loc = next(f for f in bridge.parse_template(have['template'])['field'] if f['kobo'] == 'location')
        self.assertEqual((loc['latitude'], loc['longitude']), ('latitude', 'longitude'))

    def test_select_options_come_from_the_form(self):
        self.assertNotIn('options', next(f for f in self.t['field'] if f['kobo'] == 'working'))
        t = bridge.with_form(self.t, bridge.form_choices(EVERY))
        self.assertEqual(next(f for f in t['field'] if f['kobo'] == 'working')['options'], {'yes': 'Yes', 'no': 'No'})

    def test_a_code_matches(self):
        form = {'settings': {'form_title': 'Sites'}, 'survey': [
            {'type': 'text', 'name': 'site_name'}, {'type': 'text', 'name': 'site_code'}]}
        t = bridge.parse_template(propose.propose(form, 'CSite')['template'])
        self.assertEqual((t['record']['match'], t['record']['required']), ({'siteCode': 'site_code'}, ['site_name', 'site_code']))
        self.assertNotIn('match', bridge.parse_template(propose.propose(form, 'Case')['template'])['record'])

    def test_espo_entity_prefix(self):
        m = mapping(propose.propose(EVERY, 'Account'))
        self.assertEqual((m['people'], m['site']), (('cPeople', 'int'), ('cSite', 'varchar')))


class People(unittest.TestCase):
    FORM = {'settings': {'form_title': 'Sign up'}, 'survey': [
        {'type': 'text', 'name': 'full_name', 'label': 'Name', 'required': 'true'},
        {'type': 'text', 'name': 'email', 'label': 'Email', 'required': 'true'},
        {'type': 'text', 'name': 'mobile_phone', 'label': 'Phone'},
        {'type': 'text', 'name': 'skills', 'label': 'Skills'}]}

    def test_contact_own_fields_and_match(self):
        p = propose.propose(self.FORM, 'Contact')
        t = bridge.parse_template(p['template'])
        self.assertEqual(mapping(p), {'full_name': ('name', 'personName'), 'email': ('emailAddress', None),
                                      'mobile_phone': ('phoneNumber', None), 'skills': ('cSkills', 'varchar')})
        self.assertEqual((t['record']['match'], t['record']['required'], t['record'].get('name')),
                         ({'emailAddress': 'email'}, ['email'], None))

    def test_case_requester_and_priority(self):
        form = {'settings': {'form_title': 'Help'}, 'survey': [
            {'type': 'text', 'name': 'your_name'}, {'type': 'text', 'name': 'email'},
            {'type': 'select_one', 'select_from_list_name': 'org', 'name': 'organisation'},
            {'type': 'select_one', 'select_from_list_name': 'p', 'name': 'priority'},
            {'type': 'text', 'name': 'summary'}, {'type': 'text', 'name': 'description', 'appearance': 'multiline'}],
            'choices': [{'list_name': 'p', 'name': n, 'label': n} for n in ('Low', 'Normal', 'High')]
            + [{'list_name': 'org', 'name': 'a', 'label': 'Org A'}]}
        p = propose.propose(form, 'Case', team='Support')
        t = bridge.parse_template(p['template'])
        self.assertEqual(t['requester'], {'name': 'your_name', 'email': 'email', 'organisation': 'organisation'})
        self.assertEqual(mapping(p), {'priority': ('priority', None), 'description': ('description', None)})
        self.assertEqual((t['record']['name'], t['record']['required']), ('{summary}', ['summary', 'email']))
        # Other choices than EspoCRM's priorities: a field of its own
        form['choices'][0]['name'] = 'whenever'
        self.assertEqual(mapping(propose.propose(form, 'Case'))['priority'], ('cPriority', 'enum'))


class Existing(unittest.TestCase):
    def test_reused_or_numbered(self):
        p = propose.propose(EVERY, 'CSite', existing={'people': 'int', 'notes': 'varchar', 'score': 'varchar',
                                                      'site': 'link', 'photos': 'attachmentMultiple'})
        m = mapping(p)
        self.assertEqual((m['people'], m['notes'], m['score'], m['site']),
                         (('people', None), ('notes', None), ('score2', 'float'), ('site', 'link')))
        self.assertEqual(bridge.parse_template(p['template'])['record']['media'], 'photos')
        self.assertTrue(any(w.startswith('site: a link from a list file') for w in p['warnings']))

    def test_no_name_question(self):
        form = {'settings': {'form_title': 'Counts'}, 'survey': [{'type': 'integer', 'name': 'n'}]}
        p = propose.propose(form, 'CSite')
        self.assertEqual(bridge.parse_template(p['template'])['record']['name'], 'Counts {_id}')
        self.assertEqual(len(p['warnings']), 2)  # no name, no team


class Preview(unittest.TestCase):
    def setUp(self):
        self.t = bridge.parse_template(propose.propose(EVERY, 'CSite', team='Response: North', notify=['lead'])['template'])
        self.sub = {'_id': 7, '_uuid': 'u-7', '_submission_time': '2026-11-06T10:00:00',
                    'end': '2026-11-06T11:30:00.000+01:00', 'site_name': 'Well 4', 'counts/people': '12',
                    'counts/litres_per_day': '3.5', 'working': 'no', 'risks': 'flood fire',
                    'photo': 'well.jpg', '_attachments': [{'filename': 'x/attachments/well.jpg',
                                                           'media_file_basename': 'well.jpg', 'question_xpath': 'photo'}]}

    def test_the_record_it_would_make(self):
        p = propose.preview(self.t, self.sub, EVERY)
        rec = p['record']
        self.assertEqual((p['entity'], p['teams'], p['notify'], p['files']), ('CSite', ['Response: North'], ['lead'],
                                                                               ['well.jpg']))
        self.assertEqual((rec['name'], rec['people'], rec['litresPerDay'], rec['working'], rec['risks'], rec['finishedAt']),
                         ('Well 4', 12, 3.5, 'no', ['flood', 'fire'], '2026-11-06 10:30:00'))

    def test_why_not(self):
        p = propose.preview(self.t, {**self.sub, 'site_name': ''})
        self.assertEqual(p['error'], 'required answer missing: site_name')
        p = propose.preview(self.t, {**self.sub, 'counts/people': 'many'})
        self.assertEqual(p['error'], 'people: not a number')


if __name__ == '__main__':
    unittest.main()
