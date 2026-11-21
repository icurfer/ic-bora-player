"""원격 주소가 로그/예외로 다시 노출되지 않아야 한다."""
import io
import logging
import pytest
from bora import log


@pytest.mark.parametrize('formatter',[logging.Formatter,log._PrivacyFormatter])
@pytest.mark.parametrize('message', [
    'sftp://user:password@nas.example.com:2222/share/file.mp4',
    'nfs://[fd00::12]/export/video.mp4',
    '/run/user/1000/gvfs/smb-share:server=nas.example.com,share=video/file',
    '연결 실패 ' + str(__import__('ipaddress').ip_address('10.0.0.0') + 42),
])
def test_remote_message_and_traceback_hidden(message,formatter):
    logger = log.get('privacy-test')
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter('%(message)s'))
    logger.addHandler(handler)
    logger.propagate = False
    try:
        logger.warning('오류 %s', message)
        try:
            raise OSError(message)
        except OSError:
            logger.exception('예외')
        output = stream.getvalue()
        assert message not in output
        assert 'nas.example.com' not in output and 'password' not in output
        assert 'OSError' in output
    finally:
        logger.removeHandler(handler)
        logger.propagate = True


def test_version_and_local_filename_remain_readable():
    assert log.redact('Bora 0.26.6.1 /tmp/lecture.mp4') == 'Bora 0.26.6.1 /tmp/lecture.mp4'
