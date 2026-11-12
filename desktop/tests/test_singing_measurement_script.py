"""The PJS056 reference measurement runs from files shipped with the app; no model is loaded here."""
import importlib.util
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT/'desktop/assets/alignment-demo'


def script():
    spec = importlib.util.spec_from_file_location('measure_singing_alignment', ROOT/'scripts/measure-singing-alignment.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def reverse():
    sample = json.loads((DEMO/'sample.json').read_text(encoding='utf-8'))
    return {tuple(p['phone'] for p in m['phones']): m['kana'] for m in sample['mora']}, sample


def test_bundled_song_splits_into_the_three_labelled_phrases():
    m = script(); table, sample = reverse()
    class Args: bundled = True; corpus = None; labels = None; songs = 0
    (song, lab, wav), = m.inputs(Args)
    assert song == 'pjs056' and lab.is_file() and wav.is_file()
    found = m.phrases(lab, table)
    assert [len(p) for p in found] == [4, 19, 14]
    # を and お share the phoneme o, so the reverse table can only name one of them.
    assert ''.join(x['key'] for p in found for x in p) == ''.join(x['kana'] for x in sample['mora']).replace('を', 'お')
    audio = m.read_wav(wav)
    assert audio.dtype == np.float32 and len(audio) == 16*48000


def test_seeded_ranges_repeat_and_stay_inside_the_song():
    m = script(); table, _ = reverse()
    found = m.phrases(DEMO/'pjs056.lab', table)
    import random
    for scenario in ('draft', 'tight'):
        a = m.ranges(found, 16000, scenario, random.Random(1)); b = m.ranges(found, 16000, scenario, random.Random(1))
        assert a == b and all(0 <= s < e <= 16000 for s, e in a)
        assert all(s <= p[0]['start'] + 300 and e >= p[-1]['end'] - 500 for (s, e), p in zip(a, found))


def test_errors_report_mean_absolute_and_tail_check_only_counts():
    m = script()
    human = [[{'key': 'ら', 'start': 1000, 'end': 1200}, {'key': 'く', 'start': 1200, 'end': 1500}]]
    row = {'mora': [{'start': 1010, 'end': 1190}, {'start': 1190, 'end': 1420}]}
    result = m.compare([row], human)
    assert result['line_onset']['mae_ms'] == 10 and result['line_tail']['mae_ms'] == 80 and result['syllable_onset']['n'] == 1
    assert m.stats([]) == {'n': 0}
    rate = 48000; t = np.arange(rate*2)/rate
    audio = np.where((t >= 1.0) & (t < 1.5), np.sin(2*np.pi*220*t)*.5, 0)
    samples = np.round(audio*32767).astype('<i2')
    meta = [{'song': 's', 'trial': 0, 'index': 0, 'end': 1800}]
    found = m.tail_check([row], human, meta, lambda song: samples, True)
    assert found['lines'] == 1 and found['tail_error_over_100ms'] == 0
    assert set(found) == {'lines', 'tail_error_over_100ms', 'flagged', 'flagged_and_over_100ms', 'flag_codes', 'recommended', 'candidates'}
    assert row['mora'][-1]['end'] == 1420
