import base64
from io import BytesIO
import json
import unittest
from unittest.mock import patch
import wave
import mimo_tts


def sample_wav():
    buffer = BytesIO()
    with wave.open(buffer, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b'\0\0' * 240)
    return buffer.getvalue()


class MiMoTests(unittest.TestCase):
    def test_official_contract_returns_valid_audio(self):
        audio = sample_wav()
        response = json.dumps({'choices':[{'message':{'audio':{'data':base64.b64encode(audio).decode()}}}]}).encode()
        def open_request(req, timeout):
            body = json.loads(req.data)
            self.assertEqual(req.full_url, mimo_tts.API_URL)
            self.assertEqual(body['model'], 'mimo-v2.5-tts')
            self.assertEqual(body['messages'][-1], {'role':'assistant', 'content':'你好'})
            self.assertEqual(body['audio'], {'format':'wav', 'voice':'茉莉'})
            return BytesIO(response)
        with patch.object(mimo_tts.urllib.request, 'urlopen', side_effect=open_request):
            self.assertEqual(mimo_tts.synthesize('你好', '自然', '茉莉', 'unit-test-only'), audio)

    def test_rejects_invalid_audio_and_missing_key(self):
        invalid = json.dumps({'choices':[{'message':{'audio':{'data':'invalid!'}}}]}).encode()
        with patch.object(mimo_tts.urllib.request, 'urlopen', return_value=BytesIO(invalid)):
            with self.assertRaisesRegex(ValueError, '有效 WAV'):
                mimo_tts.synthesize('你好', '', '茉莉', 'unit-test-only')
        with self.assertRaisesRegex(ValueError, 'MIMO_API_KEY'):
            mimo_tts.synthesize('你好', '', '茉莉', '')


if __name__ == '__main__':
    unittest.main()
