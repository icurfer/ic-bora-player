"""OS Secret Service. 비밀값은 평문 파일이나 로그로 대체하지 않는다."""


def _service():
    import gi
    gi.require_version('Secret', '1')
    from gi.repository import Secret
    schema = Secret.Schema.new('com.icurfer.Bora.API', Secret.SchemaFlags.NONE,
                               {'provider': Secret.SchemaAttributeType.STRING})
    return Secret, schema


def read():
    secret, schema = _service()
    return secret.password_lookup_sync(schema, {'provider': 'openai'}, None) or ''


def write(value):
    secret, schema = _service()
    if not secret.password_store_sync(schema, {'provider': 'openai'},
                                      secret.COLLECTION_DEFAULT, 'Bora OpenAI API', value, None):
        raise RuntimeError('Secret Service save failed')


def delete():
    secret, schema = _service()
    secret.password_clear_sync(schema, {'provider': 'openai'}, None)
