import ctypes,os
from shengao.process_memory import sample,_Counters


def test_memory_report_describes_own_process_and_real_current_allocations():
    before=sample();buffer=ctypes.create_string_buffer(16*1024*1024)
    for offset in range(0,len(buffer),4096):buffer[offset]=b'x'
    after=sample()
    assert before['pid']==after['pid']==os.getpid()
    assert after['working_set_bytes']>0 and after['private_bytes']>0
    assert after['peak_working_set_bytes']>=after['working_set_bytes']
    assert after['private_bytes']>=before['private_bytes']+8*1024*1024
    assert ctypes.sizeof(_Counters)==80
