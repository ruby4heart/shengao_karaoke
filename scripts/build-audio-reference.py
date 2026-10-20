"""Build a test-only reference from the original render function bodies + real wx.

This library is never distributed or loaded by the production Qt application.
It supplies independent pixel evidence, rather than comparing the port to itself.
"""
from pathlib import Path
import json
root=Path(__file__).resolve().parents[1]
source=root/'vendor'/'aegisub'/'src';target=root/'build'/'desktop-reference';target.mkdir(parents=True,exist_ok=True)
def read(name):return (source/name).read_text(encoding='utf-8')
def function(text,start):
    a=text.index(start);opening=text.index('{',a);level=1;b=opening+1
    while level:
        if text[b]=='{':level+=1
        if text[b]=='}':level-=1
        b+=1
    return text[a:b]
config=json.loads(read('libresrc/default_config.json'))
values=[]
for name in ['Icy Blue','Green']:
    for style in ['Normal','Inactive','Selection','Primary']:
        values.extend(config['Colour']['Schemes'][name][style][x] for x in ['Hue Offset','Hue Scale','Saturation Offset','Saturation Scale','Lightness Offset','Lightness Scale'])
prefix=r'''
#include <wx/init.h>
#include <wx/bitmap.h>
#include <wx/image.h>
#include <wx/dcmemory.h>
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstring>
#include <memory>
#include <unordered_map>
#include <vector>
#include "../../desktop/native/aegisub/fft.h"
void hsl_to_rgb(int,int,int,unsigned char*,unsigned char*,unsigned char*);
template<class T> T mid(T a,T b,T c){return std::clamp(b,a,c);}
enum AudioRenderingStyle {AudioStyle_Normal,AudioStyle_Inactive,AudioStyle_Selected,AudioStyle_Primary};
struct Provider {
 const int16_t *data;int64_t count;int rate;
 int GetSampleRate(){return rate;} int GetChannels(){return 1;}int GetBytesPerSample(){return 2;}
 void GetAudio(void *dest,int64_t start,int64_t length){auto p=(int16_t*)dest;for(int64_t i=0;i<length;++i)p[i]=start+i<0||start+i>=count?0:data[start+i];}
};
'''
prefix+='\nstatic double parameters[2][4][6]={'+','.join(str(x) for x in values)+'};\n'
prefix+=r'''
struct AudioColorScheme {
 std::vector<unsigned char> palette;size_t factor;
 AudioColorScheme(int precision,int scheme,int style):palette((3<<precision)+3),factor(size_t(1)<<precision){
  auto v=parameters[scheme][style];
  for(size_t i=0;i<=factor;++i){double t=double(i)/factor;
   hsl_to_rgb(mid<int>(0,v[0]+t*v[1],255),mid<int>(0,v[2]+t*v[3],255),mid<int>(0,v[4]+t*v[5],255),&palette[i*3],&palette[i*3+1],&palette[i*3+2]);}
 }
 const unsigned char *get_color(float val)const{return &palette[mid<size_t>(0,val*factor,factor)*3];}
 void map(float val,unsigned char *pixel)const{auto color=get_color(val);pixel[0]=color[0];pixel[1]=color[1];pixel[2]=color[2];}
 wxColour get(float val)const{auto color=get_color(val);return wxColour(color[0],color[1],color[2]);}
};
struct AudioSpectrumRenderer;
struct Cache {AudioSpectrumRenderer *owner;std::unordered_map<size_t,std::vector<float>> data;float &Get(size_t);};
struct AudioSpectrumRenderer {
 Provider *provider;std::unique_ptr<Cache> cache;std::vector<AudioColorScheme> colors;
 size_t derivation_size_user=9,derivation_dist_user=8,derivation_size=9,derivation_dist=8;
 std::vector<int16_t> audio_scratch;std::vector<float> fft_scratch;
 float max_freq=20000,pos_fref=.001f,freq_ref=1000,amplitude_scale=1;double pixel_ms=20;
 template<class T>void ConvertToFloat(size_t count,T *dest);
 void update_derivation_values();void FillBlock(size_t,float*);void Render(wxBitmap&,int,AudioRenderingStyle);
};
float &Cache::Get(size_t i){auto pos=data.find(i);if(pos==data.end()){auto &v=data[i];v.resize(size_t(1)<<owner->derivation_size);owner->FillBlock(i,v.data());return v[0];}return pos->second[0];}
struct AudioWaveformRenderer {
 Provider *provider;std::vector<AudioColorScheme> colors;bool render_averages=false;
 double pixel_ms=20;float amplitude_scale=1;std::unique_ptr<char[]> audio_buffer;
 void Render(wxBitmap&,int,AudioRenderingStyle);
};
'''
spectrum=read('audio_renderer_spectrum.cpp');wave=read('audio_renderer_waveform.cpp')
body='template<class T>\n'+function(spectrum,'void AudioSpectrumRenderer::ConvertToFloat(')+'\n'
for start in ['void AudioSpectrumRenderer::update_derivation_values (','void AudioSpectrumRenderer::FillBlock(','void AudioSpectrumRenderer::Render(']:body+=function(spectrum,start)+'\n'
body+=function(wave,'void AudioWaveformRenderer::Render(')+'\n'
suffix=r'''
extern "C" __declspec(dllexport) int sg_reference_render(const int16_t *samples,int64_t count,int rate,int start,int width,int height,double pixel_ms,float amplitude,int spectrum,int quality,int curve,int style,unsigned char *rgb){
 static wxInitializer init;if(!init)return 0;
 Provider provider{samples,count,rate};wxBitmap bitmap(width,height,24);
 if(spectrum==1){
  static int sizes[]={8,9,9,9,10,11},distances[]={8,8,7,6,6,5};static float positions[]={.001f,.125f,.333f,.425f,.999f};
  AudioSpectrumRenderer renderer;renderer.provider=&provider;renderer.derivation_size_user=sizes[quality];renderer.derivation_dist_user=distances[quality];renderer.update_derivation_values();
  renderer.cache=std::make_unique<Cache>();renderer.cache->owner=&renderer;
  renderer.fft_scratch.resize(6<<renderer.derivation_size);renderer.audio_scratch.resize(2<<renderer.derivation_size);
  renderer.pos_fref=positions[curve];renderer.pixel_ms=pixel_ms;renderer.amplitude_scale=amplitude;
  for(int i=0;i<4;++i)renderer.colors.emplace_back(12,0,i);
  renderer.Render(bitmap,start,static_cast<AudioRenderingStyle>(style));
 }else{
  AudioWaveformRenderer renderer;renderer.provider=&provider;renderer.pixel_ms=pixel_ms;renderer.amplitude_scale=amplitude;renderer.render_averages=spectrum==2;
  for(int i=0;i<4;++i)renderer.colors.emplace_back(6,1,i);
  renderer.Render(bitmap,start,static_cast<AudioRenderingStyle>(style));
 }
 wxImage image=bitmap.ConvertToImage();memcpy(rgb,image.GetData(),width*height*3);return 1;
}
'''
notice=spectrum[:spectrum.index('/// @file')]
(target/'reference.cpp').write_text(notice+'\n'+prefix+body+suffix,encoding='utf-8')
(target/'SOURCE-METHODS.json').write_text(json.dumps({'source':'vendor/aegisub/src; SHA256 in desktop/native/aegisub/SOURCES.json','methods':['ConvertToFloat','update_derivation_values','FillBlock','AudioSpectrumRenderer::Render','AudioWaveformRenderer::Render'],'render_bodies':'verbatim source; provider/cache/palette initialization adapted; real wxBitmap/wxMemoryDC'},indent=2),encoding='utf-8')
print(target/'reference.cpp')
