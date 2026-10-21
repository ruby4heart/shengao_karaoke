from studio_backend.model import LyricLine,Unit


def fixture():
    source=LyricLine('source','君と歌う',1000,6000,[Unit('君と',1000,2000,'キミト','Kimi-to',source='manual',locked=True),
        Unit('歌う',2000,6000,'ウタウ','UTAU!',source='manual')],kana='キミトウタウ',romaji='Kimi-to UTAU!',reviewed=True)
    target=LyricLine('target','君と歌う',15000,21000,[Unit('君',15000,16500,'きみ','kimi',reading_source='dictionary'),
        Unit('と歌う',16500,21000,'とうたう','to-utau',reading_source='dictionary')],translation='保留本段译文',display_start=14800,display_end=21400)
    return source,target
