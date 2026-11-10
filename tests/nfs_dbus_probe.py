"""사설 D-Bus에서 실제 메시지 왕복으로 인증 거부·소유권·이탈 정리 확인."""
import os
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from gi.repository import Gio, GLib
from bora.platform.linux.nfs_service import Broker, NAME, OBJECT, ACTION

connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
loop = GLib.MainLoop()
policy = {'allow': False, 'hold': False, 'pending': None, 'subjects': []}
policy_xml = '''<node><interface name="org.freedesktop.PolicyKit1.Authority">
<method name="CheckAuthorization"><arg type="(sa{sv})" direction="in"/><arg type="s" direction="in"/><arg type="a{ss}" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/><arg type="(bba{ss})" direction="out"/></method>
<method name="CancelCheckAuthorization"><arg type="s" direction="in"/></method>
</interface></node>'''

def authority(bus, sender, path, interface, method, parameters, invocation):
    if method == 'CancelCheckAuthorization':
        if policy['pending']:
            policy['pending'].return_value(GLib.Variant('((bba{ss}))', ((False, False, {}),)))
            policy['pending'] = None
        invocation.return_value(None)
        return
    subject, action, details, flags, cancellation = parameters.unpack()
    assert action == ACTION and flags == 1
    policy['subjects'].append(subject)
    if policy['hold']:
        policy['pending'] = invocation
    else:
        invocation.return_value(GLib.Variant('((bba{ss}))', ((policy['allow'], False, {}),)))

connection.register_object('/org/freedesktop/PolicyKit1/Authority',
    Gio.DBusNodeInfo.new_for_xml(policy_xml).interfaces[0], authority, None, None)
Gio.bus_own_name_on_connection(connection, 'org.freedesktop.PolicyKit1', Gio.BusNameOwnerFlags.NONE, None, None)
Gio.bus_own_name_on_connection(connection, NAME, Gio.BusNameOwnerFlags.NONE, None, None)
broker = Broker(connection, loop)

class Mounts:
    def __init__(self):
        self.entries = {}
        self.created = []
        self.released = []
    def create(self, owner, token, uri, uid):
        assert uid == os.getuid()
        self.created.append((owner, token))
        self.entries[(owner, token)] = '/run/bora-nfs/fake-owned-mount'
        return '/run/bora-nfs/fake-owned-mount'
    def release(self, owner, token):
        assert (owner, token) in self.entries
        self.released.append((owner, token))
        del self.entries[(owner, token)]
broker.mounts = Mounts()

def client():
    return Gio.DBusConnection.new_for_address_sync(os.environ['DBUS_SESSION_BUS_ADDRESS'],
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)

def wait(predicate):
    end = time.monotonic() + 4
    context = GLib.MainContext.default()
    while not predicate() and time.monotonic() < end:
        context.iteration(False)
        time.sleep(.005)
    assert predicate(), 'D-Bus response timed out'

def call(client, method, values):
    output = []
    def done(source, result):
        try:
            answer = source.call_finish(result)
            output.append(('ok', answer.unpack() if answer else None))
        except GLib.Error as error:
            output.append(('error', error.message))
    client.call(NAME, OBJECT, NAME, method, values, None, Gio.DBusCallFlags.NONE, 3000, None, done)
    return output

first, second = client(), client()
# 이름 등록 완료를 기다린다. 빈 타이머 대신 버스의 실제 NameHasOwner를 확인한다.
context = GLib.MainContext.default()
for _ in range(20):
    context.iteration(False)
    time.sleep(.005)
result = call(first, 'Mount', GLib.Variant('(ss)', ('nfs://host/export', 'a'*32)))
wait(lambda: result)
assert result[0][0] == 'error' and broker.mounts.created == []
assert policy['subjects'][0] == ('system-bus-name', {'name': first.get_unique_name()})
policy['allow'] = True
result = call(first, 'Mount', GLib.Variant('(ss)', ('nfs://host/export', 'b'*32)))
wait(lambda: result)
assert result[0][0] == 'ok'
wrong = call(second, 'Release', GLib.Variant('(s)', ('b'*32,)))
wait(lambda: wrong)
assert wrong[0][0] == 'error' and not broker.mounts.released
released = call(first, 'Release', GLib.Variant('(s)', ('b'*32,)))
wait(lambda: released)
assert released[0][0] == 'ok'
policy['hold'] = True
result = call(first, 'Mount', GLib.Variant('(ss)', ('nfs://host/export', 'c'*32)))
wait(lambda: policy['pending'] is not None)
cancelled = call(first, 'Cancel', GLib.Variant('(s)', ('c'*32,)))
wait(lambda: cancelled and result)
assert result[0][0] == 'error' and len(broker.mounts.created) == 1
policy['hold'] = False
result = call(first, 'Mount', GLib.Variant('(ss)', ('nfs://host/export', 'd'*32)))
wait(lambda: result)
assert result[0][0] == 'ok'
first.close_sync(None)
wait(lambda: not broker.mounts.entries)
assert len(broker.mounts.released) == 2
second.close_sync(None)
print('private D-Bus: denied auth, real caller subject, allowed mount, foreign release denied, cancel, disconnect cleanup passed')
