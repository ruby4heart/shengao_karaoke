// Independent scene adapter around the original BSD-licensed Aegisub drawing.
// Copyrights and unchanged methods are retained in aegisub/timeline_view.inc.
#include <wx/init.h>
#include <wx/bitmap.h>
#include <wx/image.h>
#include <wx/dcmemory.h>
#include <wx/dcgraph.h>
#include <wx/settings.h>
#include <wx/font.h>
#include <wx/event.h>
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstring>
#include <string>
#include <vector>
#include <windows.h>

#include "aegisub/timeline_colours.inc"
template<class T> T mid(T a,T b,T c){return std::clamp(b,a,c);}
static wxString sg_format(const wchar_t* fmt,int a,int b){return wxString::Format(fmt,a,b);}
static wxString sg_format(const wchar_t* fmt,double a){
    return wcschr(fmt,L'f')?wxString::Format(fmt,a):wxString::Format(fmt,static_cast<int>(a));
}
#define fmt_wx(str, ...) sg_format(wxS(str), __VA_ARGS__)
static wxString FontFace(const char*){return {};}
class UIColours {
    int scheme=0;bool focused=false;
public:
    void SetColourScheme(const std::string& name){scheme=name=="Green";}
    void SetFocused(bool value){focused=value;}
    wxColour get(int part)const{auto c=ui_colours[scheme][focused][part];return {c[0],c[1],c[2]};}
    wxColour Light()const{return get(0);} wxColour Dark()const{return get(1);} wxColour Selection()const{return get(2);}
};
struct TimeRange {int a,b;int begin()const{return a;}int end()const{return b;}int length()const{return b-a;}};
struct AudioMarker {
    enum FeetStyle{Feet_None,Feet_Left,Feet_Right,Feet_Both};
    int position,width=0;wxPen pen;FeetStyle feet=Feet_None;
    int GetPosition()const{return position;}int GetWidth()const{return width;}
    wxPen GetStyle()const{return pen;}FeetStyle GetFeet()const{return feet;}
};
using AudioMarkerVector=std::vector<const AudioMarker*>;
struct AudioLabelProvider {struct AudioLabel{wxString text;TimeRange range;};};
struct SceneController {
    std::vector<AudioMarker> markers;std::vector<AudioLabelProvider::AudioLabel> labels;
    SceneController* GetTimingController(){return this;}
    void GetMarkers(TimeRange,AudioMarkerVector& out){for(auto& m:markers)out.push_back(&m);}
    void GetLabels(TimeRange,std::vector<AudioLabelProvider::AudioLabel>& out){out=labels;}
};
struct AudioDisplayInteractionObject {virtual bool OnMouseEvent(wxMouseEvent&)=0;virtual ~AudioDisplayInteractionObject()=default;};
struct AudioDisplay {
    wxMemoryDC* dc;SceneController* controller;int audio_top,audio_height,scroll_left,foot_size=6,track_cursor_pos=-1;
    double ms_per_pixel;wxString track_cursor_label;wxRect track_cursor_label_rect;wxSize size;
    void GetTextExtent(const wxString& text,int* w,int* h){dc->GetTextExtent(text,w,h);}
    void ScrollPixelToLeft(int){} void RefreshRect(wxRect,bool){} wxSize GetClientSize(){return size;}
    int RelativeXFromTime(int ms)const{return int(ms/ms_per_pixel)-scroll_left;}
    int AbsoluteXFromTime(int ms)const{return int(ms/ms_per_pixel);}
    void PaintMarkers(wxDC&,TimeRange);void PaintFoot(wxDC&,int,int);void PaintLabels(wxDC&,TimeRange);void PaintTrackCursor(wxDC&);
};
#ifndef SG_TIMELINE_METHODS
#define SG_TIMELINE_METHODS "aegisub/timeline_view.inc"
#endif
#include SG_TIMELINE_METHODS

// All dimensions here are physical pixels, just like the original wx DC.
// The Qt adapter converts only at the boundary, including fractional DPI.
struct SGMarker {int time,width,red,green,blue,alpha,thickness,dotted,feet;};
struct SGLabel {int start,end;const char* text;};
struct SGScene {
    int width,height,duration,start_pixel,scheme,focused,selection_start,selection_end,cursor_pixel;
    double pixel_ms,dpr;
    const char* cursor_label;
};
static bool initialized(){static wxInitializer init;return bool(init);}
static wxFont scene_font(double dpr){
    wxFont font=wxSystemSettings::GetFont(wxSYS_DEFAULT_GUI_FONT);
    HDC screen=GetDC(nullptr);double scale=GetDeviceCaps(screen,LOGPIXELSY)/96.;ReleaseDC(nullptr,screen);
    font.SetFractionalPointSize(font.GetFractionalPointSize()*dpr/scale);return font;
}
extern "C" __declspec(dllexport) int sg_view_top(double dpr){
    if(!initialized())return 0;
    wxBitmap bitmap(1,1,24);wxMemoryDC dc(bitmap);dc.SetFont(scene_font(dpr));int w,h;dc.GetTextExtent("0123456789:.",&w,&h);return h+4;
}
extern "C" __declspec(dllexport) int sg_view_render(const SGScene* scene,const unsigned char* body,int body_height,const SGMarker* markers,int marker_count,const SGLabel* labels,int label_count,unsigned char* rgb){
    if(!scene||!rgb||scene->width<1||scene->height<32||scene->pixel_ms<=0||!initialized())return 0;
    try {
        wxBitmap bitmap(scene->width,scene->height,24);wxMemoryDC dc(bitmap);dc.SetFont(scene_font(scene->dpr));
        SceneController controller;
        AudioDisplay display{&dc,&controller,0,0,scene->start_pixel};display.ms_per_pixel=scene->pixel_ms;display.size={scene->width,scene->height};
        AudioDisplayTimeline timeline(&display);AudioDisplayScrollbar scrollbar(&display);
        std::string scheme=scene->scheme?"Green":"Icy Blue";
        timeline.SetColourScheme(scheme);timeline.SetDisplaySize(display.size);timeline.ChangeAudio(scene->duration);timeline.ChangeZoom(scene->pixel_ms);timeline.SetPosition(scene->start_pixel);
        display.audio_top=timeline.GetHeight();display.audio_height=scene->height-display.audio_top-15;
        if(display.audio_height<1||body_height!=display.audio_height)return 0;
        UIColours colours;colours.SetColourScheme(scheme);dc.SetBackground(wxBrush(colours.Dark()));dc.Clear();
        if(body){wxImage image(scene->width,body_height,const_cast<unsigned char*>(body),true);dc.DrawBitmap(wxBitmap(image),0,display.audio_top);}
        for(int i=0;i<marker_count;++i){auto& m=markers[i];wxPen pen(wxColour(m.red,m.green,m.blue,m.alpha),m.thickness,m.dotted?wxPENSTYLE_DOT:wxPENSTYLE_SOLID);controller.markers.push_back({m.time,m.width,pen,static_cast<AudioMarker::FeetStyle>(m.feet)});}
        for(int i=0;i<label_count;++i){auto& l=labels[i];controller.labels.push_back({wxString::FromUTF8(l.text),{l.start,l.end}});}
        TimeRange visible{std::max(0,int(scene->start_pixel*scene->pixel_ms)),int((scene->start_pixel+scene->width)*scene->pixel_ms)};
        {wxGCDC graphics(dc);display.PaintMarkers(graphics,visible);}
        display.PaintLabels(dc,visible);
        display.track_cursor_pos=scene->cursor_pixel;
        if(scene->cursor_label)display.track_cursor_label=wxString::FromUTF8(scene->cursor_label);
        if(display.track_cursor_pos>=0)display.PaintTrackCursor(dc);
        scrollbar.SetColourScheme(scheme);scrollbar.SetDisplaySize(display.size);
        scrollbar.ChangeLengths(std::max(1,int(scene->duration/scene->pixel_ms)),scene->width);scrollbar.SetPosition(scene->start_pixel);
        if(scene->selection_start>=0)scrollbar.SetSelection(int(scene->selection_start/scene->pixel_ms),int((scene->selection_end-scene->selection_start)/scene->pixel_ms));
        scrollbar.Paint(dc,scene->focused,-1);timeline.Paint(dc);
        dc.SelectObject(wxNullBitmap);wxImage output=bitmap.ConvertToImage();memcpy(rgb,output.GetData(),size_t(scene->width)*scene->height*3);return 1;
    }catch(...){return 0;}
}
