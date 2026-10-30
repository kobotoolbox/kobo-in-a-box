"""
Test scenario for templates/health-referral.toml (made-up people and places): the Kobo
form CHWs fill in at each household visit, 13 visits, and the case each one should open.
Used by test_bridge.py and e2e-espo.py.

The form works out the referral reasons itself (calculate rows), so Enketo and Collect
show the CHW where to refer. Test submissions are posted as XML, which skips the form's
logic, so `with_reasons` repeats the same rules in Python.
"""

ZONES = {f'zone_{i}': f'Zone {i}' for i in range(1, 5)}


def _choices(list_name, options):
    return [{'list_name': list_name, 'name': k, 'label': [v]} for k, v in options.items()]


def _row(type_, name, label='', **kw):
    row = {'type': type_, 'name': name, **kw}
    if label:
        row['label'] = [label]
    return row


CHILD = "${patient_type} = 'child_u5'"
REASONS = ['r_danger', 'r_pregnancy', 'r_cholera', 'r_dysentery', 'r_persistent', 'r_sam', 'r_mam']

FORM = {
    'survey': [
        _row('select_one chw', 'chw', 'Community health worker', required=True),
        _row('date', 'visit_date', 'Visit date', required=True),
        _row('select_one zone', 'zone', 'Zone', required=True),
        _row('text', 'household_id', 'Household ID (on the shelter card)'),
        _row('select_one patient_type', 'patient_type', 'Who is this visit about?', required=True),
        _row('text', 'caregiver_name', 'Name of the caregiver (or of the patient)'),
        _row('integer', 'age_months', 'Age in months', relevant=CHILD,
             constraint='. >= 0 and . < 60'),
        _row('select_one sex', 'sex', 'Sex'),
        _row('select_multiple danger', 'danger_signs', 'General danger signs', relevant=CHILD),
        _row('integer', 'muac_mm', 'MUAC (mm)', relevant=f'{CHILD} and ${{age_months}} >= 6',
             constraint='. >= 60 and . <= 250'),
        _row('select_one yes_no', 'fever', 'Fever now or in the last 2 days?'),
        _row('select_one rdt', 'rdt', 'Malaria RDT result', relevant="${fever} = 'yes'"),
        _row('select_one diarrhoea', 'diarrhoea', 'Diarrhoea'),
        _row('select_one yes_no', 'severe_dehydration',
             'Severe dehydration (sunken eyes, skin pinch goes back very slowly, unable to drink)?',
             relevant="${diarrhoea} != 'none'"),
        _row('select_multiple pregnancy_danger', 'pregnancy_danger_signs',
             'Pregnancy danger signs', relevant="${patient_type} = 'pregnant'"),
        _row('calculate', 'r_danger', calculation=(
            f"if({CHILD} and count-selected(${{danger_signs}}) > 0 and "
            "not(selected(${danger_signs}, 'none')), 'child_danger_signs', '')")),
        _row('calculate', 'r_pregnancy', calculation=(
            "if(${patient_type} = 'pregnant' and count-selected(${pregnancy_danger_signs}) > 0 "
            "and not(selected(${pregnancy_danger_signs}, 'none')), 'pregnancy_danger_signs', '')")),
        # WHO suspected cholera (no known outbreak): 2 years or older, AWD with severe dehydration
        _row('calculate', 'r_cholera', calculation=(
            "if(${diarrhoea} = 'acute_watery' and ${severe_dehydration} = 'yes' and "
            "(${patient_type} != 'child_u5' or ${age_months} >= 24), 'suspected_cholera', '')")),
        _row('calculate', 'r_dysentery', calculation="if(${diarrhoea} = 'bloody', 'dysentery', '')"),
        _row('calculate', 'r_persistent',
             calculation="if(${diarrhoea} = 'persistent', 'persistent_diarrhoea', '')"),
        _row('calculate', 'r_sam',
             calculation="if(${muac_mm} != '' and number(${muac_mm}) < 115, 'sam', '')"),
        _row('calculate', 'r_mam', calculation=(
            "if(${muac_mm} != '' and number(${muac_mm}) >= 115 and number(${muac_mm}) < 125, "
            "'mam', '')")),
        _row('calculate', 'referral_reasons', calculation='normalize-space(concat('
             + ", ' ', ".join(f'${{{r}}}' for r in REASONS) + '))'),
        _row('calculate', 'referral_needed',
             calculation="if(${referral_reasons} != '', 'yes', 'no')"),
        _row('note', 'referral_note', 'Refer now: ${referral_reasons}',
             relevant="${referral_needed} = 'yes'"),
        _row('select_one referred_to', 'referred_to', 'Referred to',
             relevant="${referral_needed} = 'yes'", required=True),
        _row('select_one yes_no', 'callback_consent',
             'May the referral team call you to check that you got care?',
             relevant="${referral_needed} = 'yes'"),
        _row('text', 'caregiver_phone', 'Phone number for the call',
             relevant="${callback_consent} = 'yes'"),
        _row('text', 'notes', 'Notes'),
    ],
    'choices': (
        _choices('chw', {'chw_amani': 'Amani Bizimana', 'chw_furaha': 'Furaha Ndayishimiye',
                         'chw_imani': 'Imani Kabura', 'chw_neema': 'Neema Hakizimana'})
        + _choices('zone', ZONES)
        + _choices('patient_type', {'child_u5': 'Child under 5', 'pregnant': 'Pregnant woman',
                                    'other': 'Other household member'})
        + _choices('sex', {'female': 'Female', 'male': 'Male'})
        + _choices('danger', {'unable_to_drink': 'Unable to drink or breastfeed',
                              'vomits_everything': 'Vomits everything',
                              'convulsions': 'Convulsions', 'lethargic': 'Lethargic or unconscious',
                              'chest_indrawing': 'Chest indrawing', 'none': 'None'})
        + _choices('yes_no', {'yes': 'Yes', 'no': 'No'})
        + _choices('rdt', {'positive': 'Positive', 'negative': 'Negative', 'not_done': 'Not done'})
        + _choices('diarrhoea', {'none': 'None', 'acute_watery': 'Acute watery',
                                 'bloody': 'Bloody', 'persistent': '14 days or more'})
        + _choices('pregnancy_danger', {'bleeding': 'Vaginal bleeding',
                                        'severe_headache': 'Severe headache or blurred vision',
                                        'fever': 'Fever', 'swelling': 'Swelling of face or hands',
                                        'reduced_movement': 'Baby moving less', 'none': 'None'})
        + _choices('referred_to', {'health_post': 'Zone health post',
                                   'hospital': 'District hospital', 'otp': 'OTP site',
                                   'tsfp': 'TSFP site', 'ctu': 'Cholera treatment unit'})
    ),
    'settings': {'default_language': 'English (en)'},
}


def with_reasons(v):
    """The form's calculate rows, for a visit posted as XML."""
    child = v.get('patient_type') == 'child_u5'
    danger = (v.get('danger_signs') or '').split()
    preg = (v.get('pregnancy_danger_signs') or '').split()
    muac = v.get('muac_mm')
    age = v.get('age_months') or 0
    reasons = [
        'child_danger_signs' if child and danger and 'none' not in danger else '',
        'pregnancy_danger_signs' if v.get('patient_type') == 'pregnant' and preg and 'none' not in preg else '',
        'suspected_cholera' if (v.get('diarrhoea') == 'acute_watery' and v.get('severe_dehydration') == 'yes'
                                and (not child or age >= 24)) else '',
        'dysentery' if v.get('diarrhoea') == 'bloody' else '',
        'persistent_diarrhoea' if v.get('diarrhoea') == 'persistent' else '',
        'sam' if muac is not None and muac < 115 else '',
        'mam' if muac is not None and 115 <= muac < 125 else '',
    ]
    out = dict(v)
    out['referral_reasons'] = ' '.join(r for r in reasons if r)
    out['referral_needed'] = 'yes' if out['referral_reasons'] else 'no'
    return out


def _visit(key, chw, zone, hh, ptype, name, sex, expect, **answers):
    return {'key': key, 'expect': expect, 'answers': {
        'chw': chw, 'visit_date': '2026-10-27', 'zone': zone, 'household_id': hh,
        'patient_type': ptype, 'caregiver_name': name, 'sex': sex, **answers}}


RC, NUT, SURV = 'Referral coordinators', 'Nutrition (OTP)', 'Surveillance'


def _case(priority, teams, hours, reasons, phone):
    return {'priority': priority, 'teams': sorted(teams), 'follow_up_hours': hours,
            'reasons': reasons, 'phone': phone}


# expect: None = no case. Batch 1 is submitted first; batch 2 after the bridge's first pass.
VISITS = [
    _visit('V01', 'chw_amani', 'zone_2', 'Z2-0147', 'child_u5', 'Josiane Ndikumana', 'female',
           _case('Urgent', [RC], 24, ['child_danger_signs'], True),
           age_months=18, danger_signs='convulsions lethargic', muac_mm=128, fever='yes',
           rdt='positive', diarrhoea='none', referred_to='hospital', callback_consent='yes',
           caregiver_phone='+255 712 400 118',
           notes='Convulsed twice this morning. Mother walking to the hospital with a neighbour.'),
    _visit('V02', 'chw_furaha', 'zone_1', 'Z1-0032', 'child_u5', 'Claudine Irakoze', 'male',
           _case('High', [NUT], 48, ['sam'], True),
           age_months=30, danger_signs='none', muac_mm=108, fever='no', diarrhoea='none',
           referred_to='otp', callback_consent='yes', caregiver_phone='+255 754 210 093'),
    _visit('V03', 'chw_furaha', 'zone_1', 'Z1-0090', 'child_u5', 'Aline Nshimirimana', 'female',
           _case('Normal', [NUT], 168, ['mam'], False),
           age_months=14, danger_signs='none', muac_mm=119, fever='no', diarrhoea='none',
           referred_to='tsfp', callback_consent='no'),
    _visit('V04', 'chw_imani', 'zone_3', 'Z3-0211', 'child_u5', 'Ange Niyonzima', 'male', None,
           age_months=9, danger_signs='none', muac_mm=131, fever='yes', rdt='positive',
           diarrhoea='none', notes='Uncomplicated malaria: first ACT dose given, revisit on day 3.'),
    _visit('V05', 'chw_imani', 'zone_3', 'Z3-0018', 'other', 'Emmanuel Hakizimana', 'male',
           _case('Urgent', [SURV], 6, ['suspected_cholera'], True),
           fever='no', diarrhoea='acute_watery', severe_dehydration='yes', referred_to='ctu',
           callback_consent='yes', caregiver_phone='+255 768 331 507',
           notes='Rice-water stools since last night. Two neighbours with the same.'),
    _visit('V06', 'chw_imani', 'zone_3', 'Z3-0019', 'child_u5', 'Diane Ndayizeye', 'female',
           _case('Urgent', [NUT, SURV], 6, ['suspected_cholera', 'sam'], True),
           age_months=40, danger_signs='none', muac_mm=112, fever='no', diarrhoea='acute_watery',
           severe_dehydration='yes', referred_to='ctu', callback_consent='yes',
           caregiver_phone='+255 768 449 120', notes='Next shelter to Z3-0018.'),
    _visit('V07', 'chw_neema', 'zone_4', 'Z4-0102', 'pregnant', 'Esperance Bigirimana', 'female',
           _case('Urgent', [RC], 24, ['pregnancy_danger_signs'], True),
           pregnancy_danger_signs='bleeding', fever='no', diarrhoea='none', referred_to='hospital',
           callback_consent='yes', caregiver_phone='+255 713 002 846',
           notes='About 7 months pregnant. Bleeding since yesterday.'),
    _visit('V08', 'chw_neema', 'zone_4', 'Z4-0131', 'pregnant', 'Sandrine Kaneza', 'female', None,
           pregnancy_danger_signs='none', fever='no', diarrhoea='none',
           notes='Next ANC visit on Monday.'),
    _visit('V09', 'chw_amani', 'zone_2', 'Z2-0150', 'child_u5', 'Pascal Niyungeko', 'male',
           _case('High', [RC], 48, ['dysentery'], True),
           age_months=24, danger_signs='none', muac_mm=126, fever='no', diarrhoea='bloody',
           severe_dehydration='no', referred_to='health_post', callback_consent='yes',
           caregiver_phone='+255 745 870 221'),
    _visit('V10', 'chw_amani', 'zone_2', 'Z2-0155', 'child_u5', 'Grace Uwimana', 'female', None,
           age_months=36, danger_signs='none', muac_mm=140, fever='no', diarrhoea='none'),
    _visit('V11', 'chw_furaha', 'zone_1', 'Z1-0101', 'child_u5', 'Jeanine Nibizi', 'male',
           _case('Urgent', [NUT, RC], 24, ['child_danger_signs', 'mam'], False),
           age_months=7, danger_signs='chest_indrawing', muac_mm=121, fever='yes', rdt='negative',
           diarrhoea='none', referred_to='health_post', callback_consent='no',
           notes='Fast breathing, chest indrawing. Caregiver has no phone.'),
    _visit('V12', 'chw_neema', 'zone_4', 'Z4-0140', 'child_u5', 'Odette Niyonkuru', 'female',
           _case('Urgent', [RC], 24, ['child_danger_signs'], True),
           age_months=5, danger_signs='unable_to_drink', fever='yes', rdt='not_done',
           diarrhoea='none', referred_to='health_post', callback_consent='yes',
           caregiver_phone='+255 789 515 640', notes='Not breastfeeding since yesterday.'),
]
LATER = [
    _visit('V13', 'chw_imani', 'zone_3', 'Z3-0240', 'child_u5', 'Fabrice Ntakirutimana', 'male',
           _case('High', [NUT, RC], 48, ['persistent_diarrhoea', 'mam'], True),
           age_months=20, danger_signs='none', muac_mm=117, fever='no', diarrhoea='persistent',
           severe_dehydration='no', referred_to='health_post', callback_consent='yes',
           caregiver_phone='+255 716 902 334', notes='Diarrhoea for about three weeks.'),
]
