#!/usr/bin/env python3
"""
KoboCollect's side of e2e-collect.sh, on the stand-in phone (phone.sh) with uiautomator2:
add the project from the account's QR code, download the form, fill it in and send it.
Prints PASS/FAIL lines, and saves a screenshot of each step (and the screen's layout when
a step fails) to <shots>.

    /opt/kobo-phone/venv/bin/python -I e2e-collect.py <shots> <qr.png> <form title> <username>

The phone has no camera, and both of Collect's QR screens close when theirs fails, so
the code is read here (zbarimg, decoded as Collect does: Base64, zlib, JSON) and its
server, username and password typed into "Manually enter project details". Collect's own
reading of the code (and the admin settings in it) needs a phone or an emulator with a
camera.
"""
import base64, json, re, subprocess, sys, time, zlib
from pathlib import Path
import uiautomator2 as u2

SHOTS, QR, FORM, USER = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
PKG = 'org.koboc.collect.android'
d = u2.connect('127.0.0.1:5555')
d.implicitly_wait(20)
step_no = 0


def rid(name):
    return d(resourceId=f'{PKG}:id/{name}')


def shot(name):
    global step_no
    step_no += 1
    d.screenshot(str(SHOTS / f'{step_no:02d}-{name}.png'))


def step(name, fn):
    """Run one step; PASS/FAIL, a screenshot, and the layout when it fails."""
    try:
        detail = fn()
        print(f'PASS  {name}' + (f' {detail}' if detail else ''), flush=True)
        shot(re.sub(r'\W+', '-', name).strip('-').lower())
        return True
    except Exception as e:  # noqa: BLE001 (any failure is the step's)
        print(f'FAIL  {name} ({type(e).__name__}: {e})', flush=True)
        shot('failed')
        (SHOTS / f'{step_no:02d}-failed.xml').write_text(d.dump_hierarchy())
        return False


def allow_dialogs():
    """Collect's permission notes and Android's permission prompts, whenever they come."""
    for _ in range(3):
        if d(resourceId='com.android.permissioncontroller:id/permission_allow_button').exists:
            d(resourceId='com.android.permissioncontroller:id/permission_allow_button').click()
        elif d(resourceId=f'{PKG}:id/permission_text').exists:
            d(resourceId='android:id/button1').click()
        else:
            return
        time.sleep(1)


def read_qr():
    raw = subprocess.run(['zbarimg', '-q', '--raw', QR], capture_output=True, text=True, check=True).stdout
    return json.loads(zlib.decompress(base64.b64decode(raw.strip())))


def add_project():
    g = read_qr()['general']
    d.shell(f'am start -W -n {PKG}/org.odk.collect.android.mainmenu.MainMenuActivity')  # app_start doesn't, here
    rid('configure_manually_button').click()
    rid('url_input_text').set_text(g['server_url'])
    rid('username_input_text').set_text(g['username'])
    rid('password_input_text').set_text(g['password'])
    d.press('back') if d(resourceId='com.android.inputmethod.latin:id/keyboard_view').exists else None
    rid('add_button').click()
    time.sleep(2)
    allow_dialogs()
    if not rid('get_forms').wait(timeout=20):
        raise RuntimeError('no main menu')
    return f"({g['server_url']}, {g['username']})"


def download_form():
    rid('get_forms').click()
    item = d(text=FORM)
    if not item.wait(timeout=60):
        raise RuntimeError('the form is not in the list')
    # Select All (the row's checkbox doesn't take a click); a tap as soon as the list
    # shows is lost, so until the box is ticked
    for _ in range(10):
        if rid('checkbox').info['checked']:
            break
        rid('toggle_button').click()
        time.sleep(1)
    rid('add_button').click()  # Get Selected
    result = dialog_text()  # its OK goes back to the main menu
    if 'succeeded' not in result:
        raise RuntimeError(result)
    return f'({result})'


def dialog_text():
    """The text of the result dialog Collect shows after downloading or sending; closes it."""
    msg = d(resourceId='android:id/message')
    if not msg.wait(timeout=90):
        raise RuntimeError('no result')
    text = ' '.join(msg.get_text().split())
    d(resourceId='android:id/button1').click()
    return text


def fill_in():
    rid('enter_data').click()
    d(text=FORM).click()
    allow_dialogs()

    def question(label):
        if not rid('text_label').wait(timeout=20) or label not in rid('text_label').get_text():
            raise RuntimeError(f'expected "{label}", got "{rid("text_label").get_text()}"')

    def next_screen():
        rid('form_forward_button').click()
        time.sleep(1)

    question('head of household')
    d(className='android.widget.EditText').set_text('Amina Kamara'); next_screen()
    question('How many people')
    d(className='android.widget.EditText').set_text('5'); next_screen()
    question('safe water')
    d(text='Yes').click(); next_screen()
    if not d(textContains='You are at the end of').wait(timeout=10):
        raise RuntimeError('not at the end of the form')


def send():
    # The end of the form: "Send" when the project sends automatically, else "Finalize"
    # and then Ready to send
    end = d(text='Send') if d(text='Send').exists else d(text='Finalize')
    label = end.get_text()
    end.click()
    if label == 'Finalize':
        rid('send_data').click()
        d(text='Select All').click()
        d(text='Send Selected').click()
    result = dialog_text()
    if 'Successful' not in result:
        raise RuntimeError(result)
    return f'({label}: {result})'


ok = (step('Collect: project from the QR code (server, username, password)', add_project)
      and step('Collect: Download form', download_form)
      and step('Collect: form filled in on the phone', fill_in)
      and step('Collect: sent', send))
sys.exit(0 if ok else 1)
