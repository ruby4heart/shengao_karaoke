// Derived from Aegisub 3.5.0 audio_renderer_spectrum.cpp and
// audio_renderer_waveform.cpp. Copyright (c) 2005-2010 Rodrigo Braz Monteiro,
// Niels Martin Hansen. Original BSD license retained in aegisub/fft.h.
// Qt adapter and bounded cache: Copyright (c) 2026 Shengao contributors. MIT.
// No wxWidgets, agi::Context, or Aegisub application dependency.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <memory>
#include <unordered_map>
#include <vector>
#include "aegisub/fft.h"

void hsl_to_rgb(int,int,int,unsigned char*,unsigned char*,unsigned char*);
#define API extern "C" __declspec(dllexport)

struct Audio {
    const int16_t *samples; int64_t count; int rate;
    int size_user=-1,dist_user=-1,size=0,dist=0;
    std::vector<float> scratch;
    std::unordered_map<int64_t,std::vector<float>> powers;
    unsigned char palettes[2][4][4097][3];
    size_t cache_limit=128*1024*1024;
    int16_t sample(int64_t i) const { return i>=0 && i<count ? samples[i] : 0; }

    // Same six resolution levels as AudioDisplay::ReloadRenderingSettings.
    void resolution(int quality) {
        static int widths[]={8,9,9,9,10,11}, distances[]={8,8,7,6,6,5};
        quality=std::clamp(quality,0,5);
        if(size_user==widths[quality] && dist_user==distances[quality]) return;
        size=size_user=widths[quality];dist=dist_user=distances[quality];
        float mult=float(rate)/50000.f;
        while(mult>1){++size;++dist;mult*=0.5f;}
        scratch.resize(6<<size);powers.clear();
    }
    const std::vector<float>& power(int64_t index) {
        auto found=powers.find(index);if(found!=powers.end())return found->second;
        if(powers.size()*(sizeof(float)<<size)>cache_limit)powers.clear();
        int64_t first_sample=(index<<dist)-(int64_t(1)<<size);
        for(size_t i=0;i<(size_t(2)<<size);++i)scratch[i]=float(sample(first_sample+i))/32768.0;
        float *input=scratch.data(),*real=input+(2<<size),*imag=input+(4<<size);
        FFT fft;fft.Transform(2<<size,input,real,imag);
        const float scale_fix=1.f/sqrtf(float(1<<(size-size_user)));
        float scale_factor=scale_fix*9/sqrt(2*(float)(2<<size));
        std::vector<float> output(1<<size);
        for(size_t i=0;i<output.size();++i)output[i]=log10(sqrt(real[i]*real[i]+imag[i]*imag[i])*scale_factor+1);
        return powers.emplace(index,std::move(output)).first->second;
    }
};

API void *sg_audio_create(const int16_t *samples,int64_t count,int sample_rate) {
    if(!samples || count<1 || sample_rate<8000 || sample_rate>384000)return nullptr;
    auto audio=new Audio;audio->samples=samples;audio->count=count;audio->rate=sample_rate;return audio;
}
// HSL parameters copied from the source's default_config.json, kept configurable.
API void sg_audio_palette(void *handle,int scheme,int style,const double *values) {
    auto a=static_cast<Audio*>(handle);scheme=std::clamp(scheme,0,1);style=std::clamp(style,0,3);
    int factor=scheme==0?4096:64;
    for(int i=0;i<=factor;++i){
        double t=double(i)/factor;auto pixel=a->palettes[scheme][style][i];
        hsl_to_rgb(std::clamp(int(values[0]+t*values[1]),0,255),std::clamp(int(values[2]+t*values[3]),0,255),std::clamp(int(values[4]+t*values[5]),0,255),pixel,pixel+1,pixel+2);
    }
}
API int sg_audio_render(void *handle,int64_t start,int width,int height,double pixel_ms,float amplitude,int spectrum,int quality,int curve,const unsigned char *styles,unsigned char *rgb) {
    auto a=static_cast<Audio*>(handle);
    if(!a || start<0 || width<1 || width>16384 || height<1 || height>4096 || pixel_ms<=0 || amplitude<0)return 0;
    if(spectrum==1){
        a->resolution(quality);
        const int bins=1<<a->size;
        const int minband=1,maxband=std::min(int(floorf(bins*20000.f/(a->rate*.5f)+.5f)),bins);
        const float scale_log=logf(maxband/minband);
        static float positions[]={.001f,.125f,.333f,.425f,.999f};
        const float pos=positions[std::clamp(curve,0,4)];
        float b_ref=std::clamp(bins*1000.f/(a->rate*.5f),1.f,float(maxband-1));
        const float linear=minband+(maxband-minband)*pos,logarithmic=minband*expf(pos*scale_log);
        float ratio=std::clamp((b_ref-linear)/(logarithmic-linear),0.f,1.f);
        struct Bin {int first,last;float fraction;bool interpolate;};
        std::vector<Bin> mapping(height);float previous=minband,current=minband;
        for(int y=0;y<height;++y){
            float next=maxband;
            if(y+1<height){float relative=float(y+1)/float(height),lin=minband+relative*(maxband-minband),log=minband*expf(relative*scale_log);next=lin+ratio*(log-lin);}
            if(next-previous<2){int first=int(floorf(current));mapping[y]={first,std::min(first+1,bins-1),current-float(first),true};}
            else mapping[y]={std::min(int(floorf((previous+current)*.5f)),bins-2),std::min(int(floorf((current+next)*.5f)),bins-1),0,false};
            previous=current;current=next;
        }
        for(int x=0;x<width;++x){
            int64_t index=int64_t((start+x)*pixel_ms*a->rate/1000) >> a->dist;
            auto const& power=a->power(index);int style=std::clamp(int(styles[x]),0,3);
            for(int y=0;y<height;++y){
                auto b=mapping[y];float value;
                if(b.interpolate)value=power[b.first]+b.fraction*(power[b.last]-power[b.first]);
                else value=*std::max_element(power.begin()+b.first,power.begin()+b.last);
                auto color=a->palettes[0][style][std::clamp(int(value*amplitude*4096),0,4096)];
                memcpy(rgb+((height-1-y)*width+x)*3,color,3);
            }
        }
    }
    else{
        int midpoint=height/2;double pixel_samples=pixel_ms*a->rate/1000.0,cur=start*pixel_samples;
        for(int x=0;x<width;++x){
            auto const& palette=a->palettes[1][std::clamp(int(styles[x]),0,3)];
            for(int y=0;y<height;++y)memcpy(rgb+(y*width+x)*3,palette[0],3);
            int minimum=0,maximum=0;int64_t first=int64_t(cur),average_min=0,average_max=0;cur+=pixel_samples;
            for(int64_t i=0;i<int64_t(pixel_samples);++i){int sample=a->sample(first+i);minimum=std::min(minimum,sample);maximum=std::max(maximum,sample);if(sample>0)average_max+=sample;else average_min+=sample;}
            minimum=std::max(int(minimum*amplitude*midpoint)/0x8000,-midpoint);maximum=std::min(int(maximum*amplitude*midpoint)/0x8000,midpoint);
            // GDI/wx DrawLine excludes the final endpoint; retain exact pixels.
            int top=std::clamp(midpoint-maximum,0,height),bottom=std::clamp(midpoint-minimum,0,height);
            for(int y=top;y<bottom;++y)memcpy(rgb+(y*width+x)*3,palette[int(.4f*64)],3);
            if(spectrum==2){
                int lo=std::max(int(average_min*amplitude*midpoint/pixel_samples)/0x8000,-midpoint);
                int hi=std::min(int(average_max*amplitude*midpoint/pixel_samples)/0x8000,midpoint);
                for(int y=std::max(0,midpoint-hi);y<std::min(height,midpoint-lo);++y)memcpy(rgb+(y*width+x)*3,palette[int(.7f*64)],3);
            }
            memcpy(rgb+(midpoint*width+x)*3,palette[spectrum==2?64:int(.4f*64)],3);
        }
    }
    return 1;
}
API int sg_audio_power(void *handle,int quality,int64_t index,float *output,int capacity) {
    auto a=static_cast<Audio*>(handle);a->resolution(quality);auto const& data=a->power(index);
    if(capacity<int(data.size()))return -int(data.size());memcpy(output,data.data(),data.size()*sizeof(float));return int(data.size());
}
API void sg_audio_destroy(void *handle) { delete static_cast<Audio*>(handle); }
