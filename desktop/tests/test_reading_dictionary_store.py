import pytest
from studio_backend.reading_dictionary import put
from shengao.reading_dictionary_store import DictionaryStore


def test_personal_dictionary_roundtrip_and_undo(tmp_path):
    store=DictionaryStore(tmp_path/'home');store.save(put({},'星','せかい','特殊唱法'))
    assert DictionaryStore(tmp_path/'home').read()['entries'][0]['kana']=='せかい'
    store.export_file(tmp_path/'读音词典.json');other=DictionaryStore(tmp_path/'other')
    other.save(other.import_file(tmp_path/'读音词典.json'));assert other.read()==store.read()
    store.undo_save();assert store.read()=={}


def test_corrupt_existing_file_is_not_overwritten_and_foreign_edit_blocks_undo(tmp_path):
    store=DictionaryStore(tmp_path);store.path.write_text('not-json',encoding='utf-8')
    with pytest.raises(ValueError,match='原文件已保留'):store.save(put({},'星','せかい'))
    assert store.path.read_text()=='not-json'
    store.path.write_text('{}');store.save(put({},'星','せかい'));store.path.write_text('{}')
    with pytest.raises(ValueError,match='别处修改'):store.undo_save()
