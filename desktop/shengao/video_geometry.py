"""Display geometry shared by preview, cache validation and final encoding."""
from fractions import Fraction
import math,re

# Expand the non-square-pixel axis before subtitle rasterization. This keeps
# the stored samples rather than reducing the opposite axis. Even dimensions
# are required by the shipped CPU H.264 encoder; square/even sources pass as is.
SQUARE_FILTER="scale=w='ceil(iw*max(1,if(gt(sar,0),sar,1))/2)*2':h='ceil(ih*max(1,if(gt(sar,0),1/sar,1))/2)*2',setsar=1"


def video_stream(log):
    return next((line for line in log.splitlines() if 'Stream #' in line and 'Video:' in line and 'attached pic' not in line.lower()),'')


def geometry(log):
    line=video_stream(log);size=re.search(r'Video:.*? (\d{2,5})x(\d{2,5})(?:[ ,\[])',line)
    width,height=(int(size[1]),int(size[2])) if size else (1920,1080)
    sar=re.search(r'\bSAR\s+(\d+):(\d+)',line);ratio=Fraction(int(sar[1]),int(sar[2])) if sar and int(sar[1])>0 and int(sar[2])>0 else Fraction(1)
    section=[];selected=False
    for entry in log.splitlines():
        if entry==line and line:selected=True;continue
        if selected and ('Stream #' in entry or entry.startswith('Output #')):break
        if selected:section.append(entry)
    found=re.search(r'rotation of\s+([-+\d.]+)\s+degrees','\n'.join(section),re.I);angle=float(found[1])%360 if found else 0
    if not math.isfinite(angle):raise ValueError('视频显示方向无效')
    if math.isclose(angle,round(angle),abs_tol=.00001):angle=int(round(angle))%360
    display_width=math.ceil(width*max(1,ratio)/2)*2;display_height=math.ceil(height*max(1,1/ratio)/2)*2
    if angle in (90,270):display_width,display_height=display_height,display_width
    if not 16<=display_width<=8192 or not 16<=display_height<=8192:raise ValueError('视频显示尺寸超出16至8192像素范围，请检查素材的像素比例')
    return {'coded_width':width,'coded_height':height,'sar_num':ratio.numerator,'sar_den':ratio.denominator,
            'rotation_ccw':angle,'display_width':display_width,'display_height':display_height}
