"""대화 원본을 유지하고 해당 답변의 질문을 연결한다."""
from copy import deepcopy

from bora.ai.study import qa_text, transcript, pending_transcript, message_marker
from bora.ai.history import Conversation


def test_answer_uses_reply_id_not_latest_question():
    first = {'role': 'user', 'id': 'one', 'content': '첫 질문'}
    second = {'role': 'user', 'id': 'two', 'content': '두 번째 질문'}
    answer = {'role': 'assistant', 'reply_to': 'one', 'content': '첫 답변', 'timestamp': 12}
    messages = [first, second, answer]
    before = deepcopy(messages)
    result = qa_text(messages, answer)
    assert '첫 질문' in result and '첫 답변' in result and '두 번째 질문' not in result
    assert '[00:00:12]' in result
    assert messages == before


def test_legacy_answer_does_not_pick_later_question():
    answer = {'role': 'assistant', 'content': '이전 답변'}
    result = qa_text([answer, {'role': 'user', 'content': '미래 질문'}], answer)
    assert '연결된 질문이 없습니다' in result and '미래 질문' not in result


def test_legacy_pair_and_interrupted_answer():
    question = {'role': 'user', 'content': '질문', 'attachments': ['capture.png']}
    answer = {'role': 'assistant', 'content': '중간 답변', 'status': 'interrupted'}
    result = qa_text([question, answer], answer)
    assert all(text in result for text in ['질문', '중간 답변', '미완료', 'capture.png'])


def test_transcript_preserves_unanswered_question_and_all_turns(tmp_path):
    history = Conversation(tmp_path / '강의.mp4', directory=tmp_path / 'history')
    history.messages = [{'id': str(i), 'role': 'user', 'content': f'질문 {i}'} for i in range(25)]
    history.save()
    reopened = Conversation(tmp_path / '강의.mp4', directory=tmp_path / 'history')
    result = transcript(reopened.messages)
    assert result.count('###') == 25 and '질문 24' in result and '질문 0' in result
    assert history.messages == reopened.messages


def test_export_retains_local_image_links_without_external_paths():
    result = transcript([{'role': 'user', 'content': '장면 설명', 'image_refs':
                         ['강의.assets/장면 (1).png', '../outside.png', '/etc/passwd', 'https://example.com/x']}])
    assert result.count('![대화 첨부]') == 1
    assert '%28' in result and 'outside' not in result and 'https:' not in result


def test_auto_notes_keep_timestamps_and_only_append_new_turns():
    messages = [{'role': 'user', 'content': '질문', 'timestamp': 13},
                {'role': 'assistant', 'content': '답변', 'timestamp': 13}]
    saved = '사용자가 작성한 생각\n' + pending_transcript(messages, '')
    assert '[00:00:13]' in saved and '질문' in saved and '답변' in saved
    assert pending_transcript(deepcopy(messages), saved) == ''
    messages.append({'role': 'user', 'content': '다음 질문', 'timestamp': 27})
    added = pending_transcript(messages, saved)
    assert '[00:00:27]' in added and '다음 질문' in added and '답변' not in added


def test_identical_legacy_turns_are_not_dropped():
    message = {'role': 'user', 'content': '한 번 더', 'timestamp': 0}
    messages = [message, deepcopy(message)]
    first = pending_transcript(messages[:1], '')
    second = pending_transcript(messages, first)
    assert message_marker(message, 0) != message_marker(message, 1)
    assert second.count('한 번 더') == 1


def test_auto_notes_keep_unanswered_and_interrupted_turns():
    messages = [{'role': 'user', 'content': '아직 답변 없는 질문', 'timestamp': 21},
                {'role': 'assistant', 'content': '중지한 답변', 'status': 'interrupted', 'timestamp': 21}]
    before = deepcopy(messages)
    text = pending_transcript(messages, '')
    assert '미완료' in text and '아직 답변 없는 질문' in text
    assert messages == before
